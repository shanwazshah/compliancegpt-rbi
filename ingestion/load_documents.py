"""Load the scraped manifest into the Postgres `documents` table.

This is the "documents populated" step of Phase 1. Most fields come straight
from the scraper's regex-extracted manifest; richer LLM-extracted fields
(subject_tags, cross-references) are added in a later phase.

All 30 NBFC MDs are from the Nov 2025 consolidation and currently in force, so
they load with status='active'. Supersession edges come in Phase 2.

Run:  python -m ingestion.load_documents
"""

from __future__ import annotations

import json
from pathlib import Path

from app.db.queries import count_documents, get_connection, upsert_document

MANIFEST = Path("data") / "nbfc_manifest.json"


def load() -> None:
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    with get_connection() as conn:
        for rec in records:
            doc = {
                "source_regulator": "RBI",
                "doc_type": "master_direction",
                "doc_number": rec["doc_number"],
                "title": rec["title"],
                "issue_date": rec["issue_date"],
                "status": "active",
                "source_url": rec["detail_url"],
                "pdf_storage_path": rec["pdf_path"],
                "entity_categories": ["NBFC"],
                "raw_text_hash": rec["raw_text_hash"],
            }
            doc_id = upsert_document(conn, doc)
            print(f"  upserted {doc['doc_number']} -> {doc_id}")
        print(f"\ndocuments table now holds {count_documents(conn)} rows")


if __name__ == "__main__":
    load()
