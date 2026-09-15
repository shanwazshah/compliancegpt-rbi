"""Export the reviewed PageIndex pilot corpus for the hosted Streamlit app."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from psycopg.rows import dict_row

from app.config import settings
from app.db.queries import get_connection


OUTPUT = Path("streamlit_data/corpus.json")


def _json_default(value):
    if isinstance(value, (date, datetime, UUID)):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _rows(conn, sql: str) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return [dict(row) for row in cur.fetchall()]


def main() -> None:
    with get_connection() as conn:
        documents = _rows(
            conn,
            """
            SELECT d.id::text, d.doc_number, d.title, d.source_url, d.issue_date,
                   d.effective_date, d.withdrawn_date, d.status
            FROM documents d
            WHERE EXISTS (
                SELECT 1 FROM document_versions v
                WHERE v.document_id=d.id AND v.index_kind='pageindex'
            )
            ORDER BY d.doc_number
            """,
        )
        versions = _rows(
            conn,
            """
            SELECT v.id::text, v.document_id::text, v.content_hash, v.valid_from,
                   v.valid_to, v.validity_basis, v.index_kind
            FROM document_versions v
            WHERE v.index_kind='pageindex'
            ORDER BY v.document_id, v.valid_from
            """,
        )
        pages = _rows(
            conn,
            """
            SELECT p.version_id::text, p.page_number, p.printed_label, p.text, p.text_hash
            FROM evidence_pages p JOIN document_versions v ON v.id=p.version_id
            WHERE v.index_kind='pageindex'
            ORDER BY p.version_id, p.page_number
            """,
        )
        nodes = _rows(
            conn,
            """
            SELECT n.version_id::text, n.node_id, n.parent_id, n.title, n.summary,
                   n.page_start, n.page_end
            FROM document_nodes n JOIN document_versions v ON v.id=n.version_id
            WHERE v.index_kind='pageindex'
            ORDER BY n.version_id, n.page_start, n.node_id
            """,
        )
        relations = _rows(
            conn,
            """
            SELECT r.id::text, s.canonical_name AS source, o.canonical_name AS target,
                   o.kind AS target_kind, r.predicate, r.evidence_quote,
                   r.source_version_id::text, r.source_page, r.valid_from, r.valid_to
            FROM kg_relations r
            JOIN kg_entities s ON s.id=r.subject_id
            JOIN kg_entities o ON o.id=r.object_id
            WHERE r.review_status='verified'
              AND r.source_version_id IN (
                  SELECT id FROM document_versions WHERE index_kind='pageindex'
              )
            ORDER BY r.id
            """,
        )
        supersession_edges = _rows(
            conn,
            """
            SELECT e.id::text, e.predecessor_doc_id::text, e.successor_doc_id::text,
                   e.relation_type, e.effective_date, e.extraction_method
            FROM supersession_edges e
            WHERE e.predecessor_doc_id IN (
                SELECT document_id FROM document_versions WHERE index_kind='pageindex'
            )
            ORDER BY e.id
            """,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT revision FROM evidence_revision WHERE singleton")
            revision = str(cur.fetchone()[0])

    payload = {
        "schema_version": 1,
        "corpus_revision": revision,
        "documents": documents,
        "versions": versions,
        "pages": pages,
        "nodes": nodes,
        "relations": relations,
        "supersession_edges": supersession_edges,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default),
        encoding="utf-8",
    )
    print(
        f"Exported {len(documents)} documents, {len(pages)} pages, "
        f"{len(nodes)} nodes and {len(relations)} verified graph relations to {OUTPUT}"
    )


if __name__ == "__main__":
    main()
