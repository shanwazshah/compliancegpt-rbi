"""Cross-encoder reranking.

A bi-encoder (our dense/BM25 retrievers) embeds query and document separately.
A cross-encoder scores the (query, chunk) PAIR jointly, which is more accurate
but too slow to run over the whole corpus — so we run it only over a small
candidate pool and keep the top_n.

Model is loaded lazily and cached. Spec's intended reranker is bge-reranker-v2-m3
(~2.2GB); the MVP uses a small MiniLM cross-encoder to fit disk (config-swappable).
"""

from __future__ import annotations

from app.config import settings

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder

        _reranker = CrossEncoder(settings.reranker_model, max_length=512)
    return _reranker


def rerank(query: str, candidates: list[dict], top_n: int = 8) -> list[dict]:
    """Score each candidate against the query with the cross-encoder; return top_n."""
    if not candidates:
        return []
    pairs = [(query, c["text"]) for c in candidates]
    scores = _get_reranker().predict(pairs)
    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
        c["score"] = float(s)  # expose the rerank score as the primary score
    return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)[:top_n]
