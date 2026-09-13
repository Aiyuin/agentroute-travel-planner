"""Small inspectable BM25 + structured + optional dense retrieval with RRF."""

import asyncio
import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path

from travel.config import travel_settings


def tokens(text: str) -> list[str]:
    # Character bigrams make the Chinese baseline independent of a tokenizer download.
    text = "".join(text.lower().split())
    return [text[i : i + 2] for i in range(max(0, len(text) - 1))]


def bm25(query: str, documents: list[dict]) -> list[str]:
    counts = [Counter(tokens(d["text"])) for d in documents]
    average = sum(map(lambda c: sum(c.values()), counts)) / max(1, len(counts))
    scores = []
    for doc, count in zip(documents, counts, strict=True):
        score = 0.0
        for term in set(tokens(query)):
            df = sum(term in c for c in counts)
            tf = count[term]
            if tf:
                idf = math.log(1 + (len(counts) - df + 0.5) / (df + 0.5))
                score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * sum(count.values()) / average))
        if score:
            scores.append((score, doc["id"]))
    return [doc_id for _, doc_id in sorted(scores, reverse=True)]


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(dict.fromkeys(ranking), 1):
            scores[doc_id] = scores.get(doc_id, 0) + 1 / (k + rank)
    return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))


@lru_cache(maxsize=1)
def cross_encoder(model_name: str):
    from sentence_transformers import CrossEncoder  # type: ignore[missing-import]

    return CrossEncoder(model_name)


async def retrieve(city: str, query: str, model=None) -> dict:
    documents = json.loads(Path(__file__).with_name("knowledge.json").read_text())
    documents = [d for d in documents if d["city"] in (city, "通用")]
    queries = [query]
    warnings = []
    if travel_settings.query_expansion and model is not None:
        try:
            reply = await asyncio.wait_for(
                model.ainvoke(
                    "将旅行检索问题改写，并写一段假设性攻略用于检索；不要输出真实事实断言。问题："
                    + query
                ),
                10,
            )
            queries.append(str(reply.content)[:1500])
        except Exception:
            warnings.append("query_expansion_unavailable")
    rankings = [bm25(q, documents) for q in queries]
    rankings.append([d["id"] for d in documents if d["city"] == city])
    channels = ["bm25", "structured"]
    if travel_settings.embedding_model:
        try:
            from langchain_openai import OpenAIEmbeddings

            from core import settings

            embedder = OpenAIEmbeddings(
                model=travel_settings.embedding_model,
                api_key=settings.COMPATIBLE_API_KEY,
                base_url=settings.COMPATIBLE_BASE_URL,
                check_embedding_ctx_length=False,
                max_retries=0,
            )
            vectors = await asyncio.wait_for(
                embedder.aembed_documents([query] + [d["text"] for d in documents]), 12
            )
            q = vectors[0]

            def cosine(v):
                return sum(a * b for a, b in zip(q, v, strict=True)) / max(
                    1e-12, math.sqrt(sum(a * a for a in q) * sum(b * b for b in v))
                )

            rankings.append(
                [
                    d["id"]
                    for _, d in sorted(
                        zip([cosine(v) for v in vectors[1:]], documents, strict=True),
                        key=lambda pair: pair[0],
                        reverse=True,
                    )
                ]
            )
            channels.append("dense")
        except Exception:
            warnings.append("dense_unavailable")
    ranked = rrf(rankings)
    lookup = {d["id"]: d for d in documents}
    candidates = [lookup[doc_id] for doc_id in ranked[:8]]
    if travel_settings.cross_encoder_model and candidates:
        # CPU inference is moved off the event loop; use only on a suitably sized host.
        try:

            def rerank():
                encoder = cross_encoder(travel_settings.cross_encoder_model)
                scores = encoder.predict([(query, d["text"]) for d in candidates])
                return [
                    d
                    for _, d in sorted(
                        zip(scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True
                    )
                ]

            candidates = await asyncio.to_thread(rerank)
            channels.append("cross_encoder")
        except Exception:
            warnings.append("reranker_unavailable")
    return {
        "source": "local_knowledge",
        "channels": channels,
        "warnings": warnings,
        "data": candidates[:3],
    }
