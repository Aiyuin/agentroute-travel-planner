"""Deterministic diagnostics, not a substitute for human itinerary review."""


def score_plan(plan: dict, days: int, budget: float, preference_terms: list[str]) -> dict:
    daily = plan.get("days", [])
    complete = [d.get("day") for d in daily] == list(range(1, days + 1)) and all(
        all(d.get(slot) for slot in ("morning", "afternoon", "evening")) for d in daily
    )
    costs = plan.get("costs", {})
    names = ("accommodation", "food", "local_transport", "tickets", "other")
    valid = all(isinstance(costs.get(n), (int, float)) and costs[n] >= 0 for n in names)
    total = sum(costs[n] for n in names) if valid else None
    text = str(daily)
    return {
        "completeness": float(complete),
        "preference_keyword_recall": sum(term in text for term in preference_terms)
        / len(preference_terms)
        if preference_terms
        else None,
        "budget_consistency": float(
            valid
            and total is not None
            and total <= budget
            and (days > 1 or costs["accommodation"] == 0)
        ),
        "estimated_total": total,
    }
