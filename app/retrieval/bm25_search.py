"""BM25 (keyword/lexical) retrieval.

Dense search matches meaning; BM25 matches exact terms — regulation numbers,
legal phrases like "capital adequacy", "wilful defaulter". Running both and
fusing them (see hybrid_search) beats either alone.

The chunk texts already live in Qdrant payloads, so we build the BM25 index by
scrolling the collection once and caching it in memory (868 chunks tokenizes
instantly). A persistent store (SQLite FTS5 / OpenSearch) is the production
upgrade noted in the spec; in-memory is plenty at this corpus size.
"""

from __future__ import annotations

import re

from qdrant_client import QdrantClient
from rank_bm25 import BM25Okapi

from app.config import settings

_bm25: BM25Okapi | None = None
_payloads: list[dict] | None = None


def _tokenize(text: str) -> list[str]:
    # Lowercase word tokens; keeps alphanumerics like "bc99" together.
    return re.findall(r"\w+", text.lower())


def _build_index() -> tuple[BM25Okapi, list[dict]]:
    # Generous timeout: scrolling the whole collection can be slow on a cold start.
    client = QdrantClient(url=settings.qdrant_url, timeout=60)
    payloads: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=settings.qdrant_collection,
            limit=256,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        payloads.extend(p.payload for p in points)
        if offset is None:
            break
    corpus = [_tokenize(p["text"]) for p in payloads]
    return BM25Okapi(corpus), payloads


def bm25_search(
    query: str, k: int = 8, allowed_doc_numbers: set[str] | None = None
) -> list[dict]:
    """Return the top-k chunks by BM25 score (payload dicts + score).

    When allowed_doc_numbers is given, only chunks from those documents (the
    temporal in-force set) are returned.
    """
    global _bm25, _payloads
    if _bm25 is None:
        _bm25, _payloads = _build_index()
    scores = _bm25.get_scores(_tokenize(query))
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    results = []
    for i in order:
        doc_number = _payloads[i]["doc_number"]
        if allowed_doc_numbers is not None and doc_number not in allowed_doc_numbers:
            continue
        results.append({"score": float(scores[i]), **_payloads[i]})
        if len(results) >= k:
            break
    return results
