"""Embed document chunks with BGE-M3 and upsert them into Qdrant.

Pipeline per document:  parse (cached) -> chunk -> embed child chunks ->
upsert vectors + payload into Qdrant.

Phase 1 is dense-only retrieval, so we embed and store the CHILD chunks (the
precise ones we search over). The payload carries everything the answer step
needs — chunk text, doc_number, title, status, issue_date — so Phase 1 doesn't
need the Postgres `chunks` table yet.

Point IDs are deterministic (UUID5 of doc_number + chunk_index) so re-running is
idempotent: the same chunk overwrites its own point instead of duplicating.

Run:  python -m ingestion.indexing.embed_and_upsert
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client import models as qm

from app.config import settings
from app.embeddings import embed_texts
from ingestion.indexing.chunking import chunk_markdown
from ingestion.parsing.pdf_to_structured import parse_pdf

MANIFEST = Path("data") / "nbfc_manifest.json"
_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-00000000c0de")


def _ensure_collection(client: QdrantClient) -> None:
    """Create the Qdrant collection, recreating it if the vector size changed.

    Recreating on a dimension mismatch means switching embedding models (e.g.
    bge-small 384-dim <-> bge-m3 1024-dim) just works without a manual wipe.
    """
    name = settings.qdrant_collection
    if client.collection_exists(name):
        current = client.get_collection(name).config.params.vectors.size
        if current == settings.embedding_dim:
            return
        print(f"Vector size changed ({current} -> {settings.embedding_dim}); recreating collection")
        client.delete_collection(name)
    client.create_collection(
        collection_name=name,
        vectors_config=qm.VectorParams(
            size=settings.embedding_dim,
            distance=qm.Distance.COSINE,  # cosine similarity on normalized vectors
        ),
    )
    print(f"Created Qdrant collection '{name}' (dim={settings.embedding_dim})")


def embed_document(client: QdrantClient, rec: dict) -> int:
    """Parse -> chunk -> embed -> upsert one document. Returns #child chunks."""
    md = parse_pdf(rec["pdf_path"])
    all_chunks = chunk_markdown(md)
    # parent (section) text, keyed by the parent chunk's index — for small-to-big.
    parent_text_by_index = {c.chunk_index: c.text for c in all_chunks if c.is_parent}
    children = [c for c in all_chunks if not c.is_parent]
    if not children:
        return 0

    vectors = embed_texts([c.text for c in children])

    points = []
    for chunk, vec in zip(children, vectors):
        point_id = str(uuid.uuid5(_NAMESPACE, f"{rec['doc_number']}:{chunk.chunk_index}"))
        points.append(
            qm.PointStruct(
                id=point_id,
                vector=vec,  # embed_texts() already returns plain lists
                payload={
                    "doc_number": rec["doc_number"],
                    "title": rec["title"],
                    "source_url": rec["detail_url"],
                    "status": "active",
                    "issue_date": rec["issue_date"],
                    "entity_categories": ["NBFC"],
                    "section_heading": chunk.section_heading,
                    "chunk_index": chunk.chunk_index,
                    "parent_index": chunk.parent_index,
                    "text": chunk.text,
                    # Fuller section text for parent expansion at generation time.
                    "parent_text": parent_text_by_index.get(chunk.parent_index, chunk.text),
                },
            )
        )
    client.upsert(collection_name=settings.qdrant_collection, points=points)
    return len(points)


def index_all() -> None:
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # Generous timeout: collection create/delete and batch upserts can exceed the
    # client default on a busy or cold Qdrant (a ReadTimeout here killed a run).
    client = QdrantClient(url=settings.qdrant_url, timeout=120)
    _ensure_collection(client)

    total_chunks = 0
    for i, rec in enumerate(records, 1):
        if not rec.get("pdf_path") or not Path(rec["pdf_path"]).exists():
            print(f"  [{i}/{len(records)}] {rec['doc_number']}  SKIP (no PDF)")
            continue
        n = embed_document(client, rec)
        total_chunks += n
        print(f"  [{i}/{len(records)}] {rec['doc_number']}  {n} chunks")

    info = client.get_collection(settings.qdrant_collection)
    print(f"\nDone. {total_chunks} chunks embedded; Qdrant reports {info.points_count} points.")


if __name__ == "__main__":
    index_all()
