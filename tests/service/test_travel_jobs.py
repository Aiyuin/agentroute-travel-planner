from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from travel import jobs
from travel.config import travel_settings


@pytest.mark.asyncio
async def test_disabled_jobs_reject_without_enqueue(monkeypatch):
    monkeypatch.setattr(travel_settings, "jobs_enabled", False)
    with pytest.raises(HTTPException) as error:
        await jobs.submit(jobs.JobInput(message="杭州"))
    assert error.value.status_code == 503


@pytest.mark.asyncio
async def test_expired_job_is_404(monkeypatch):
    monkeypatch.setattr(travel_settings, "jobs_enabled", True)
    redis = AsyncMock()
    redis.exists.return_value = False
    monkeypatch.setattr(jobs.Redis, "from_url", lambda *args, **kwargs: redis)
    with pytest.raises(HTTPException) as error:
        await jobs.known_job(uuid4())
    assert error.value.status_code == 404
    redis.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_job_graph_emits_progress_and_final_answer(monkeypatch):
    from langchain_core.messages import AIMessage
    from langgraph.graph import END, START, MessagesState, StateGraph

    from agents import travel_assistant as module

    graph = StateGraph(MessagesState)
    graph.add_node("reply", lambda state: {"messages": [AIMessage(content="test answer")]})
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    monkeypatch.setattr(module, "builder", graph)
    redis = AsyncMock()
    monkeypatch.setattr(jobs.Redis, "from_url", lambda *args, **kwargs: redis)
    result = await jobs.execute("test input", str(uuid4()))
    assert result["message"] == "test answer"
    redis.xadd.assert_awaited_once()
    redis.expire.assert_awaited_once()
