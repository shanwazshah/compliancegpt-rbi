"""Retrieval strategy dispatcher.

One entry point so the pipeline (and the ablation harness) can switch between
retrieval strategies by name.
"""

from __future__ import annotations

from app.retrieval.bm25_search import bm25_search
from app.retrieval.dense_search import dense_search
from app.retrieval.hybrid_search import hybrid_search

STRATEGIES = ("dense", "bm25", "hybrid")


def retrieve(query: str, k: int = 8, strategy: str = "hybrid") -> list[dict]:
    if strategy == "dense":
        return dense_search(query, k=k)
    if strategy == "bm25":
        return bm25_search(query, k=k)
    if strategy == "hybrid":
        return hybrid_search(query, k=k)
    raise ValueError(f"unknown retrieval strategy: {strategy!r} (choose from {STRATEGIES})")
