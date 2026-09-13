"""Isolated asynchronous planning jobs; each job has its own conversation."""

import asyncio
import json
from contextlib import suppress
from typing import cast
from uuid import UUID, uuid4

from celery import Celery
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from langgraph.types import StreamMode
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from travel.config import travel_settings

celery_app = Celery(
    "agentroute", broker=travel_settings.redis_url, backend=travel_settings.redis_url
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_soft_time_limit=180,
    task_time_limit=200,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)
router = APIRouter(prefix="/travel/jobs", tags=["travel jobs"])


class JobInput(BaseModel):
    message: str = Field(min_length=1, max_length=6000)


async def execute(message: str, job_id: str) -> dict:
    from agents.travel_assistant import builder

    redis = Redis.from_url(travel_settings.redis_url, decode_responses=True)
    try:
        result = {}
        graph = builder.compile()
        modes: list[StreamMode] = ["updates", "values"]
        async for mode, payload in graph.astream(
            {"messages": [HumanMessage(content=message)]},
            {"configurable": {"thread_id": job_id}},
            stream_mode=modes,
        ):
            if mode == "updates":
                for node in payload:
                    await redis.xadd(
                        f"travel:events:{job_id}", {"event": json.dumps({"node": node})}, maxlen=100
                    )
                    await redis.expire(f"travel:events:{job_id}", 3600)
            else:
                result = cast(dict, payload)
        return {
            "message": str(result["messages"][-1].content),
            "plan": result.get("plan", {}),
            "error": result.get("error"),
        }
    finally:
        await redis.aclose()


@celery_app.task(name="travel.plan")
def plan_job(message: str, job_id: str) -> dict:
    # No automatic retry: repeating a partially completed LLM job costs money.
    return asyncio.run(execute(message, job_id))


def ensure_enabled():
    if not travel_settings.jobs_enabled:
        raise HTTPException(503, "Set TRAVEL_JOBS_ENABLED and start Redis + worker")


@router.post("", status_code=202)
async def submit(body: JobInput):
    ensure_enabled()
    job_id = str(uuid4())
    redis = Redis.from_url(travel_settings.redis_url, decode_responses=True)
    try:
        await redis.set(f"travel:job:{job_id}", "1", ex=3600)
        await asyncio.to_thread(plan_job.apply_async, args=[body.message, job_id], task_id=job_id)
    except Exception:
        with suppress(Exception):
            await redis.delete(f"travel:job:{job_id}")
        raise HTTPException(503, "Queue unavailable") from None
    finally:
        await redis.aclose()
    return {"job_id": job_id, "events_url": f"/travel/jobs/{job_id}/events"}


async def known_job(job_id: UUID):
    ensure_enabled()
    redis = Redis.from_url(travel_settings.redis_url, decode_responses=True)
    try:
        if not await redis.exists(f"travel:job:{job_id}"):
            raise HTTPException(404, "Job unknown or expired")
    finally:
        await redis.aclose()


@router.get("/{job_id}")
async def status(job_id: UUID):
    await known_job(job_id)
    result = celery_app.AsyncResult(str(job_id))
    state = await asyncio.to_thread(lambda: result.state)
    output = await asyncio.to_thread(lambda: result.result) if state == "SUCCESS" else None
    return {"job_id": str(job_id), "state": state, "result": output}


@router.get("/{job_id}/events")
async def events(job_id: UUID):
    await known_job(job_id)

    async def stream():
        redis = Redis.from_url(travel_settings.redis_url, decode_responses=True)
        cursor = "0-0"
        try:
            for _ in range(240):
                rows = await redis.xread({f"travel:events:{job_id}": cursor}, block=1000, count=100)
                for _, entries in rows:
                    for cursor, fields in entries:
                        yield f"id: {cursor}\nevent: progress\ndata: {fields['event']}\n\n"
                result = celery_app.AsyncResult(str(job_id))
                state = await asyncio.to_thread(lambda: result.state)
                if state in ("SUCCESS", "FAILURE", "REVOKED"):
                    yield f"event: done\ndata: {json.dumps({'state': state})}\n\n"
                    return
                yield ": heartbeat\n\n"
            yield 'event: timeout\ndata: {"retry": true}\n\n'
        finally:
            await redis.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
