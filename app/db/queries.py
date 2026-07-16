"""Database access helpers (psycopg v3).

Kept deliberately small and framework-free: plain SQL through a single
connection helper. Everything that touches Postgres goes through here so the
connection string is read from config in exactly one place.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import psycopg

from app.config import settings


@contextmanager
def get_connection():
    """Yield a Postgres connection; commits on success, rolls back on error."""
    conn = psycopg.connect(settings.database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_document(conn: psycopg.Connection, rec: dict[str, Any]) -> str:
    """Insert or update one document row; return its UUID.

    Idempotent on (source_regulator, doc_number): re-running ingestion updates
    the existing row instead of creating duplicates.
    """
    sql = """
        INSERT INTO documents (
            source_regulator, doc_type, doc_number, title,
            issue_date, status, source_url, pdf_storage_path,
            entity_categories, raw_text_hash
        )
        VALUES (
            %(source_regulator)s, %(doc_type)s, %(doc_number)s, %(title)s,
            %(issue_date)s, %(status)s, %(source_url)s, %(pdf_storage_path)s,
            %(entity_categories)s, %(raw_text_hash)s
        )
        ON CONFLICT (source_regulator, doc_number) DO UPDATE SET
            title            = EXCLUDED.title,
            issue_date       = EXCLUDED.issue_date,
            status           = EXCLUDED.status,
            source_url       = EXCLUDED.source_url,
            pdf_storage_path = EXCLUDED.pdf_storage_path,
            entity_categories= EXCLUDED.entity_categories,
            raw_text_hash    = EXCLUDED.raw_text_hash,
            updated_at       = now()
        RETURNING id;
    """
    with conn.cursor() as cur:
        cur.execute(sql, rec)
        return str(cur.fetchone()[0])


def count_documents(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM documents")
        return cur.fetchone()[0]


def insert_query_log(conn: psycopg.Connection, rec: dict[str, Any]) -> None:
    """Persist one query log row (query_text must already be PII-redacted)."""
    sql = """
        INSERT INTO query_logs (query_text, reference_date, in_force_docs,
                                cited_doc_numbers, answer_text, degraded,
                                verified_citations, latency_ms)
        VALUES (%(query_text)s, %(reference_date)s, %(in_force_docs)s,
                %(cited_doc_numbers)s, %(answer_text)s, %(degraded)s,
                %(verified_citations)s, %(latency_ms)s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, rec)


def get_document(conn: psycopg.Connection, doc_id: str) -> dict | None:
    """Return one document as a dict, or None if not found."""
    sql = """
        SELECT id, source_regulator, doc_type, doc_number, title,
               issue_date, status, source_url, entity_categories
        FROM documents WHERE id = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (doc_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c.name for c in cur.description]
        doc = dict(zip(cols, row))
        doc["id"] = str(doc["id"])
        doc["issue_date"] = doc["issue_date"].isoformat() if doc["issue_date"] else None
        return doc


def supersession_history(conn: psycopg.Connection, doc_id: str) -> dict:
    """Return this document's predecessors and successors (one hop each)."""
    predecessors_sql = """
        SELECT d.id, d.doc_number, d.title, e.relation_type, e.effective_date
        FROM supersession_edges e
        JOIN documents d ON d.id = e.predecessor_doc_id
        WHERE e.successor_doc_id = %s
    """
    successors_sql = """
        SELECT d.id, d.doc_number, d.title, e.relation_type, e.effective_date
        FROM supersession_edges e
        JOIN documents d ON d.id = e.successor_doc_id
        WHERE e.predecessor_doc_id = %s
    """

    def _rows(sql: str) -> list[dict]:
        with conn.cursor() as cur:
            cur.execute(sql, (doc_id,))
            out = []
            for r in cur.fetchall():
                out.append(
                    {
                        "id": str(r[0]),
                        "doc_number": r[1],
                        "title": r[2],
                        "relation_type": r[3],
                        "effective_date": r[4].isoformat() if r[4] else None,
                    }
                )
            return out

    return {"predecessors": _rows(predecessors_sql), "successors": _rows(successors_sql)}
