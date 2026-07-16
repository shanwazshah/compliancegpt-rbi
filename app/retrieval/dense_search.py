"""Dense (semantic) retrieval over Qdrant.

Phase 1 = dense-only: embed the question with the same BGE-M3 model used at
ingestion, then ask Qdrant for the nearest chunk vectors (cosine similarity).
Hybrid (dense + keyword) retrieval and the temporal pre-filter arrive in Phase 2.
"""

from __future__ import annotations

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.config import settings
from app.embeddings import embed_query

_client: QdrantClient | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        # Generous timeout: the default is tight and a busy/cold Qdrant can
        # exceed it, surfacing as a ReadTimeout mid-query.
        _client = QdrantClient(url=settings.qdrant_url, timeout=30)
    return _client


def dense_search(
    query: str, k: int = 8, allowed_doc_numbers: set[str] | None = None
) -> list[dict]:
    """Return the top-k most semantically similar chunks as payload dicts.

    Each result includes a `score` (higher = closer) plus the chunk payload
    (text, doc_number, title, section_heading, ...). When allowed_doc_numbers is
    given, results are pre-filtered to those documents (the temporal in-force set)
    inside Qdrant — so superseded docs never enter the top-k.
    """
    query_filter = None
    if allowed_doc_numbers is not None:
        match = qm.MatchAny(any=list(allowed_doc_numbers))
        query_filter = qm.Filter(must=[qm.FieldCondition(key="doc_number", match=match)])
    query_vector = embed_query(query)
    response = _get_client().query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=k,
        with_payload=True,
        query_filter=query_filter,
    )
    return [{"score": point.score, **point.payload} for point in response.points]
