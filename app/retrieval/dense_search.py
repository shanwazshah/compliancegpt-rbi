"""Dense (semantic) retrieval over Qdrant.

Phase 1 = dense-only: embed the question with the same BGE-M3 model used at
ingestion, then ask Qdrant for the nearest chunk vectors (cosine similarity).
Hybrid (dense + keyword) retrieval and the temporal pre-filter arrive in Phase 2.
"""

from __future__ import annotations

from qdrant_client import QdrantClient

from app.config import settings
from app.embeddings import embed_query

_client: QdrantClient | None = None


def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=settings.qdrant_url)
    return _client


def dense_search(query: str, k: int = 8) -> list[dict]:
    """Return the top-k most semantically similar chunks as payload dicts.

    Each result includes a `score` (higher = closer) plus the chunk payload
    (text, doc_number, title, section_heading, ...).
    """
    query_vector = embed_query(query)
    response = _get_client().query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=k,
        with_payload=True,
    )
    return [{"score": point.score, **point.payload} for point in response.points]
