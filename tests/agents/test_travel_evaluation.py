from travel.evaluation import score_plan


def test_invalid_budget_and_missing_day_fail():
    assert score_plan({}, 2, 500, ["博物馆"])["completeness"] == 0
    assert score_plan({}, 2, 500, ["博物馆"])["budget_consistency"] == 0


def test_one_day_lodging_is_not_consistent():
    costs = dict(accommodation=50, food=20, local_transport=10, tickets=0, other=0)
    result = score_plan(
        {
            "costs": costs,
            "days": [{"day": 1, "morning": "博物馆", "afternoon": "休息", "evening": "晚餐"}],
        },
        1,
        500,
        ["博物馆"],
    )
    assert result["completeness"] == 1
    assert result["preference_keyword_recall"] == 1
    assert result["budget_consistency"] == 0
