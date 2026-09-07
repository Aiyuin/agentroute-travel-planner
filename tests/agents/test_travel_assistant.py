from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from agents import travel_assistant as travel_module
from agents.travel_assistant import (
    CostEstimate,
    DailyPlan,
    TravelPlan,
    TripRequirements,
    builder,
    validate_requirements,
)


def sample_plan(days=3):
    return TravelPlan(
        days=[
            DailyPlan(day=day, morning="景点 A", afternoon="景点 B", evening="晚餐")
            for day in range(1, days + 1)
        ],
        costs=CostEstimate(accommodation=600, food=300, local_transport=100, tickets=200, other=50),
    )


def configured_model(extractor, planner):
    model = MagicMock()

    def structured(schema, **kwargs):
        runnable = MagicMock()
        runnable.with_config.return_value = extractor if schema is TripRequirements else planner
        return runnable

    model.with_structured_output.side_effect = structured
    return model


def async_runnable(*, return_value=None, side_effect=None):
    runnable = MagicMock()
    runnable.ainvoke = AsyncMock(return_value=return_value, side_effect=side_effect)
    return runnable


@pytest.mark.parametrize("days,budget", [(0, 100), (6, 100), (2.5, 100), (3, 0), (3, -1)])
def test_invalid_values(days, budget):
    assert validate_requirements(TripRequirements(destination="杭州", days=days, budget=budget))


@pytest.mark.asyncio
async def test_followup_correction_and_isolation(monkeypatch):
    extractor = AsyncMock()
    extractor.ainvoke.side_effect = [
        TripRequirements(destination="杭州", days=3),
        TripRequirements(destination="杭州", days=3, budget=1500),
        TripRequirements(destination="杭州", days=3, budget=-1),
        TripRequirements(),
    ]
    planner = async_runnable(return_value=sample_plan())
    model = configured_model(extractor, planner)
    monkeypatch.setattr(travel_module, "selected_model", lambda config: model)
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "first"}}
    first = await graph.ainvoke({"messages": [HumanMessage(content="杭州三天")]}, config)
    assert "预算" in first["messages"][-1].content
    planner.ainvoke.assert_not_awaited()
    second = await graph.ainvoke({"messages": [HumanMessage(content="1500元")]}, config)
    assert "学习版参考行程" in second["messages"][-1].content
    assert "估算总额：**¥1,250**" in second["messages"][-1].content
    assert "预算剩余：**¥250**" in second["messages"][-1].content
    assert "住宿（默认 2 晚）" in second["messages"][-1].content
    assert len(second["messages"]) == 4
    inputs = extractor.ainvoke.call_args.args[0]
    assert [m.content for m in inputs if isinstance(m, HumanMessage)] == ["杭州三天", "1500元"]
    third = await graph.ainvoke({"messages": [HumanMessage(content="预算改成负一元")]}, config)
    assert "预算必须大于 0" in third["messages"][-1].content
    assert planner.ainvoke.await_count == 1
    fresh = await graph.ainvoke(
        {"messages": [HumanMessage(content="我的预算是多少？")]},
        {"configurable": {"thread_id": "second"}},
    )
    assert fresh["requirements"]["budget"] is None
    assert "1500" not in fresh["messages"][-1].content


@pytest.mark.asyncio
async def test_extraction_failure_returns_message(monkeypatch):
    extractor = async_runnable(side_effect=TimeoutError())
    model = configured_model(extractor, async_runnable())
    monkeypatch.setattr(travel_module, "selected_model", lambda config: model)
    state = await builder.compile().ainvoke({"messages": [HumanMessage(content="杭州")]})
    assert "暂时无法解析" in state["messages"][-1].content
    assert state["requirements"] == {}


@pytest.mark.asyncio
async def test_generation_failure_preserves_requirements(monkeypatch):
    extractor = async_runnable(
        return_value=TripRequirements(destination="杭州", days=3, budget=1500)
    )
    model = configured_model(extractor, async_runnable(side_effect=TimeoutError()))
    monkeypatch.setattr(travel_module, "selected_model", lambda config: model)
    state = await builder.compile().ainvoke({"messages": [HumanMessage(content="杭州三天1500元")]})
    assert "结果校验暂时失败" in state["messages"][-1].content
    assert state["requirements"]["budget"] == 1500


@pytest.mark.asyncio
async def test_rejects_wrong_number_of_days(monkeypatch):
    extractor = async_runnable(
        return_value=TripRequirements(destination="杭州", days=3, budget=1500)
    )
    model = configured_model(extractor, async_runnable(return_value=sample_plan(days=2)))
    monkeypatch.setattr(travel_module, "selected_model", lambda config: model)
    state = await builder.compile().ainvoke({"messages": [HumanMessage(content="杭州三天1500元")]})
    assert "结果校验暂时失败" in state["messages"][-1].content


@pytest.mark.asyncio
async def test_one_day_plan_rejects_accommodation(monkeypatch):
    extractor = async_runnable(
        return_value=TripRequirements(destination="苏州", days=1, budget=500)
    )
    model = configured_model(extractor, async_runnable(return_value=sample_plan(days=1)))
    monkeypatch.setattr(travel_module, "selected_model", lambda config: model)
    state = await builder.compile().ainvoke({"messages": [HumanMessage(content="苏州一日游500元")]})
    assert "结果校验暂时失败" in state["messages"][-1].content
