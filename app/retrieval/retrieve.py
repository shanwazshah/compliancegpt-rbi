"""Retrieval strategy dispatcher.

One entry point so the pipeline (and the ablation harness) can switch between
retrieval strategies by name.
"""

from __future__ import annotations

from app.retrieval.bm25_search import bm25_search
from app.retrieval.dense_search import dense_search
from app.retrieval.hybrid_search import candidate_pool, hybrid_search

STRATEGIES = ("dense", "bm25", "hybrid", "hybrid_rerank")


def retrieve(
    query: str,
    k: int = 8,
    strategy: str = "dense",
    allowed_doc_numbers: set[str] | None = None,
) -> list[dict]:
    """Retrieve top-k chunks. `allowed_doc_numbers` restricts to the temporal
    in-force set (pre-filter); None means no temporal restriction."""
    if strategy == "dense":
        return dense_search(query, k=k, allowed_doc_numbers=allowed_doc_numbers)
    if strategy == "bm25":
        return bm25_search(query, k=k, allowed_doc_numbers=allowed_doc_numbers)
    if strategy == "hybrid":
        return hybrid_search(query, k=k, allowed_doc_numbers=allowed_doc_numbers)
    if strategy == "hybrid_rerank":
        # Retrieve a wide candidate pool (dense ∪ BM25), then rerank precisely.
        from app.retrieval.rerank import rerank

        pool = candidate_pool(query, candidates=30, allowed_doc_numbers=allowed_doc_numbers)
        return rerank(query, pool, top_n=k)
    raise ValueError(f"unknown retrieval strategy: {strategy!r} (choose from {STRATEGIES})")
