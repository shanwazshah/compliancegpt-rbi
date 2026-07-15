"""Shared embedding model.

Both ingestion (embedding chunks) and serving (embedding the user's question)
MUST use the same model, or the vectors live in different "meaning spaces" and
search returns garbage. Centralizing it here guarantees that.

The model is loaded lazily and cached, so importing this module stays cheap and
the (heavy) weights load only on first real use.
"""

from __future__ import annotations

from app.config import settings

_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts into normalized dense vectors."""
    vecs = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text])[0]
