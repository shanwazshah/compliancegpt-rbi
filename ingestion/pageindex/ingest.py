"""Import local PDFs as versioned evidence; optionally build official PageIndex trees.

Default validity starts at today's capture date, not the PDF's original issue date.
Use --valid-from only after verifying that this exact PDF text applied on that date.
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date
from pathlib import Path

from psycopg.types.json import Jsonb

from app.config import settings
from app.db.queries import get_connection, upsert_document
from ingestion.pageindex.adapter import build_tree, normalize_tree
from ingestion.parsing.page_evidence import PARSER_VERSION, snapshot_pdf


def ingest_document(
    conn, record: dict, valid_from: date | None = None, with_pageindex: bool = False
) -> dict:
    start = valid_from or date.today()
    issue = date.fromisoformat(record["issue_date"])
    if start < issue:
        raise ValueError("Content validity cannot precede issue_date")
    digest, snapshot, pages = snapshot_pdf(
        Path(record["pdf_path"]), Path(settings.evidence_storage_path)
    )
    version = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{record['doc_number']}:{digest}:{start}"))
    # Expensive indexing happens before the publication transaction changes data.
    with conn.cursor() as cur:
        cur.execute("SELECT index_kind FROM document_versions WHERE id=%s", (version,))
        existing = cur.fetchone()
    if existing and (existing[0] == "pageindex" or not with_pageindex):
        return {"version_id": version, "pages": len(pages), "cached": True}
    nodes, metadata = [], {}
    if with_pageindex:
        tree, metadata = build_tree(snapshot)
        nodes = normalize_tree(tree, len(pages))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM documents WHERE doc_number=%s AND source_regulator=%s",
            (record["doc_number"], record.get("source_regulator", "RBI")),
        )
        document = cur.fetchone()
    doc_id = (
        str(document[0])
        if document
        else upsert_document(
            conn,
            {
                "source_regulator": record.get("source_regulator", "RBI"),
                "doc_type": record.get("doc_type", "master_direction"),
                "doc_number": record["doc_number"],
                "title": record["title"],
                "issue_date": record["issue_date"],
                "status": record.get("status", "active"),
                "source_url": record["detail_url"],
                "pdf_storage_path": str(snapshot),
                "entity_categories": record.get("entity_categories", ["NBFC"]),
                "raw_text_hash": digest,
            },
        )
    )
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO document_versions
               (id, document_id, content_hash, pdf_path, valid_from, validity_basis,
                parser_version, index_kind, index_metadata)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT(id) DO UPDATE SET index_kind=EXCLUDED.index_kind,
                    index_metadata=EXCLUDED.index_metadata, updated_at=now()""",
            (
                version,
                doc_id,
                digest,
                str(snapshot),
                start,
                "verified" if valid_from else "observed_at",
                PARSER_VERSION,
                "pageindex" if with_pageindex else "pages",
                Jsonb(metadata),
            ),
        )
        for page in pages:
            cur.execute(
                """INSERT INTO evidence_pages VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT(version_id,page_number) DO NOTHING""",
                (
                    version,
                    page["page_number"],
                    page["printed_label"],
                    page["text"],
                    page["text_hash"],
                ),
            )
        for node in nodes:
            cur.execute(
                """INSERT INTO document_nodes
                   (version_id,node_id,parent_id,title,summary,page_start,page_end)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                (
                    version,
                    node["node_id"],
                    node["parent_id"],
                    node["title"],
                    node["summary"],
                    node["page_start"],
                    node["page_end"],
                ),
            )
        cur.execute("UPDATE evidence_revision SET revision=revision+1 WHERE singleton")
    return {"version_id": version, "pages": len(pages), "cached": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("data/nbfc_manifest.json"))
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--valid-from", type=date.fromisoformat)
    parser.add_argument(
        "--pageindex",
        action="store_true",
        help="Build trees with the configured LLM (provider charges may apply)",
    )
    parser.add_argument(
        "--tree-mode",
        choices=("full", "layout"),
        default=None,
        help="Explicit PageIndex mode: full LLM refinement or local layout tree",
    )
    args = parser.parse_args()
    if args.tree_mode is not None:
        settings.pageindex_tree_mode = args.tree_mode
    if args.limit < 1:
        parser.error("--limit must be positive")
    records = json.loads(args.manifest.read_text(encoding="utf-8"))
    for record in records[: args.limit]:
        with get_connection() as conn:
            result = ingest_document(conn, record, args.valid_from, args.pageindex)
        print(record["doc_number"], result)


if __name__ == "__main__":
    main()
