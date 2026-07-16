"""Hybrid retrieval = dense + BM25, merged with Reciprocal Rank Fusion (RRF).

RRF avoids the problem of combining incompatible score scales (cosine similarity
vs BM25 term-frequency scores). It uses only each result's *rank position*:

    rrf_score(chunk) = sum over retrievers of  1 / (rrf_k + rank)

A chunk ranked highly by EITHER retriever floats to the top; a chunk ranked
highly by BOTH wins decisively. rrf_k (default 60) damps the influence of very
low ranks. This is the project's signature retrieval technique (spec §13).
"""

from __future__ import annotations

from app.retrieval.bm25_search import bm25_search
from app.retrieval.dense_search import dense_search

RRF_K = 60


def _chunk_key(hit: dict) -> tuple:
    """Unique id for a chunk across both retrievers."""
    return (hit["doc_number"], hit["chunk_index"])


def candidate_pool(query: str, candidates: int = 30) -> list[dict]:
    """Deduplicated union of dense + BM25 candidates (for a reranker to score)."""
    pool: dict[tuple, dict] = {}
    for ranked_list in (dense_search(query, k=candidates), bm25_search(query, k=candidates)):
        for hit in ranked_list:
            pool.setdefault(_chunk_key(hit), hit)
    return list(pool.values())


def hybrid_search(query: str, k: int = 8, candidates: int = 30) -> list[dict]:
    """Fuse dense + BM25 candidate lists via RRF; return top-k chunks."""
    dense = dense_search(query, k=candidates)
    sparse = bm25_search(query, k=candidates)

    rrf: dict[tuple, float] = {}
    payloads: dict[tuple, dict] = {}
    for ranked_list in (dense, sparse):
        for rank, hit in enumerate(ranked_list, start=1):
            key = _chunk_key(hit)
            rrf[key] = rrf.get(key, 0.0) + 1.0 / (RRF_K + rank)
            payloads.setdefault(key, hit)

    top_keys = sorted(rrf, key=lambda key: rrf[key], reverse=True)[:k]
    results = []
    for key in top_keys:
        hit = dict(payloads[key])
        hit["score"] = round(rrf[key], 6)  # replace with the fused RRF score
        results.append(hit)
    return results
