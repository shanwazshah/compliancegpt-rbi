"""Lazy retrieval dispatch: vectorless modes do not import vector dependencies."""

from __future__ import annotations

from app.retrieval.types import STRATEGIES


def retrieve(
    query: str,
    k: int = 8,
    strategy: str = "dense",
    allowed_doc_numbers: set[str] | None = None,
    reference_date: str | None = None,
) -> list[dict]:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown retrieval strategy: {strategy!r}")
    if k <= 0 or allowed_doc_numbers == set():
        return []
    if strategy in {"lexical", "pageindex", "graph_pageindex"}:
        from app.retrieval.pageindex_search import search

        return search(query, k, strategy, allowed_doc_numbers, reference_date)
    if strategy == "dense":
        from app.retrieval.dense_search import dense_search

        return dense_search(query, k=k, allowed_doc_numbers=allowed_doc_numbers)
    if strategy == "bm25":
        from app.retrieval.bm25_search import bm25_search

        return bm25_search(query, k=k, allowed_doc_numbers=allowed_doc_numbers)
    from app.retrieval.hybrid_search import candidate_pool, hybrid_search

    if strategy == "hybrid":
        return hybrid_search(query, k=k, allowed_doc_numbers=allowed_doc_numbers)
    from app.retrieval.rerank import rerank

    pool = candidate_pool(query, candidates=30, allowed_doc_numbers=allowed_doc_numbers)
    return rerank(query, pool, top_n=k)
