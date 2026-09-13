"""Run with PYTHONPATH=src python scripts/evaluate_travel.py; no network calls."""

import asyncio
import json
from pathlib import Path

from travel.config import travel_settings
from travel.rag import retrieve


async def main():
    travel_settings.embedding_model = None
    travel_settings.cross_encoder_model = None
    travel_settings.query_expansion = False
    cases = json.loads(Path("evals/retrieval.json").read_text())
    results = []
    for case in cases:
        data = await retrieve(case["city"], case["query"])
        ids = [d["id"] for d in data["data"]]
        results.append({**case, "actual": ids, "hit_at_3": case["expected"] in ids})
    report = {
        "mode": "offline_bm25_structured",
        "cases": results,
        "recall_at_3": sum(r["hit_at_3"] for r in results) / len(results),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["recall_at_3"] < 1:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
