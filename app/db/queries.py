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
