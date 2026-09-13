import asyncio

from travel.config import travel_settings
from travel.providers import amap, map_evidence, mcp_evidence
from travel.rag import retrieve


async def collect(kind: str, requirements: dict) -> dict:
    if not travel_settings.enabled:
        return {"status": "disabled", "data": []}
    city = requirements["destination"]
    try:
        async with asyncio.timeout(25):
            if kind == "knowledge":
                model = None
                if travel_settings.query_expansion:
                    from core import get_model, settings

                    model = get_model(settings.DEFAULT_MODEL)
                result = await retrieve(
                    city, city + " " + (requirements.get("preferences") or "旅行预算"), model
                )
            elif kind == "attractions" and travel_settings.mcp_url:
                try:
                    result = await asyncio.wait_for(mcp_evidence(city), 10)
                except Exception:
                    result = await map_evidence(kind, city)
                    result["fallback"] = "mcp_to_rest"
            elif kind == "route":
                pois = await amap.search(city, "景点")
                points = [p["location"] for p in pois if p.get("location")]
                if len(points) < 2:
                    raise ValueError("insufficient_coordinates")
                data = await amap.get("direction/walking", origin=points[0], destination=points[1])
                result = {
                    "source": "amap_walking",
                    "data": {"points": pois[:2], "route": data.get("route", {})},
                    "scope": "候选景点前两点步行参考，不是最终行程全路线",
                }
            else:
                result = await map_evidence(kind, city)
        return {"status": "ok", **result}
    except Exception as exc:
        return {"status": "unavailable", "reason": type(exc).__name__, "data": []}
