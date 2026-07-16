"""Semantic cache for repeated/near-duplicate queries (spec §13).

Keyed by the query embedding (not exact string), so paraphrases hit the same
entry. Because embeddings are normalized, cosine similarity is just a dot
product. Scoped by reference_date so a "today" answer never serves a past-date
query. In-memory + simple; a production cache would persist and add TTLs.
"""

from __future__ import annotations

from app.embeddings import embed_query


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class SemanticCache:
    def __init__(self, threshold: float = 0.97, max_size: int = 256) -> None:
        self.threshold = threshold
        self.max_size = max_size
        # entries: list of (embedding, reference_date, response)
        self._entries: list[tuple[list[float], str | None, dict]] = []

    def get(self, question: str, reference_date: str | None) -> dict | None:
        if not self._entries:
            return None
        vec = embed_query(question)
        for emb, ref, response in reversed(self._entries):  # newest first
            if ref == reference_date and _dot(vec, emb) >= self.threshold:
                return response
        return None

    def put(self, question: str, reference_date: str | None, response: dict) -> None:
        self._entries.append((embed_query(question), reference_date, response))
        if len(self._entries) > self.max_size:
            self._entries.pop(0)
