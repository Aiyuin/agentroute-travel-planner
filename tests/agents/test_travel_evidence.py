import asyncio

import pytest

from travel.config import travel_settings
from travel.evidence import collect
from travel.providers import Amap, ProviderUnavailable
from travel.rag import bm25, retrieve, rrf


def test_rrf_merges_duplicates():
    assert rrf([["a", "b", "a"], ["b", "c"]]) == ["b", "a", "c"]


def test_bm25_relevance():
    docs = [{"id": "a", "text": "杭州西湖步行"}, {"id": "b", "text": "北京长城交通"}]
    assert bm25("西湖步行", docs)[0] == "a"


@pytest.mark.asyncio
async def test_retrieval_city_filter_and_provenance(monkeypatch):
    monkeypatch.setattr(travel_settings, "embedding_model", None)
    monkeypatch.setattr(travel_settings, "cross_encoder_model", None)
    result = await retrieve("杭州", "西湖步行")
    assert result["channels"] == ["bm25", "structured"]
    assert result["data"][0]["id"] == "hz-walk"
    assert all(d["source"] and d["city"] in ("杭州", "通用") for d in result["data"])


@pytest.mark.asyncio
async def test_missing_key_degrades(monkeypatch):
    monkeypatch.setattr(travel_settings, "enabled", True)
    monkeypatch.setattr(travel_settings, "amap_key", None)
    result = await collect("weather", {"destination": "杭州"})
    assert result["status"] == "unavailable"
    with pytest.raises(ProviderUnavailable):
        await Amap().get("place/text")


@pytest.mark.asyncio
async def test_parallel_graph_survives_one_failure(monkeypatch):
    from langchain_core.messages import HumanMessage
    from test_travel_assistant import async_runnable, configured_model, sample_plan

    from agents import travel_assistant as module

    model = configured_model(
        async_runnable(
            return_value=module.TripRequirements(destination="杭州", days=3, budget=1500)
        ),
        async_runnable(return_value=sample_plan()),
    )
    monkeypatch.setattr(module, "selected_model", lambda config: model)
    arrived = set()
    barrier = asyncio.Event()

    async def fake_collect(kind, requirements):
        arrived.add(kind)
        if len(arrived) == 5:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), 2)
        return {"status": "unavailable" if kind == "weather" else "ok", "data": []}

    monkeypatch.setattr(module, "collect", fake_collect)
    state = await module.builder.compile().ainvoke(
        {"messages": [HumanMessage(content="杭州三天1500")]}
    )
    assert len(arrived) == 5
    assert state["plan"]
    assert state["weather"]["status"] == "unavailable"
