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
                                verified_citations, latency_ms,
                                prompt_tokens, completion_tokens, token_cost,
                                groundedness_score, cache_hit, llm_model)
        VALUES (%(query_text)s, %(reference_date)s, %(in_force_docs)s,
                %(cited_doc_numbers)s, %(answer_text)s, %(degraded)s,
                %(verified_citations)s, %(latency_ms)s,
                %(prompt_tokens)s, %(completion_tokens)s, %(token_cost)s,
                %(groundedness_score)s, %(cache_hit)s, %(llm_model)s)
    """
    # Tolerate callers that predate migration 0003's columns.
    row = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "token_cost": None,
        "groundedness_score": None,
        "cache_hit": False,
        "llm_model": None,
        **rec,
    }
    with conn.cursor() as cur:
        cur.execute(sql, row)


def insert_feedback(
    conn: psycopg.Connection,
    query_log_id: str,
    rating: int,
    comment: str | None = None,
) -> bool:
    """Record feedback for a logged query; False if that query_log_id is unknown."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM query_logs WHERE id = %s", (query_log_id,))
        if cur.fetchone() is None:
            return False
        cur.execute(
            """
            INSERT INTO query_feedback (query_log_id, rating, comment)
            VALUES (%s, %s, %s)
            """,
            (query_log_id, rating, comment),
        )
        return True


def insert_eval_run(conn: psycopg.Connection, rec: dict[str, Any]) -> str:
    """Record one eval run (spec §9); returns its id.

    Metrics that were not computed must be passed as None, never 0.0 — CI
    compares against thresholds, and a missing metric recorded as zero would
    fail the build for the wrong reason (or, worse, pass a later comparison).
    """
    sql = """
        INSERT INTO eval_runs (git_commit_sha, retrieval_strategy, golden_set_size,
                               recall_at_5, mrr, citation_accuracy, temporal_correctness,
                               refusal_correctness, faithfulness, answer_relevancy,
                               raw_results_path, notes)
        VALUES (%(git_commit_sha)s, %(retrieval_strategy)s, %(golden_set_size)s,
                %(recall_at_5)s, %(mrr)s, %(citation_accuracy)s, %(temporal_correctness)s,
                %(refusal_correctness)s, %(faithfulness)s, %(answer_relevancy)s,
                %(raw_results_path)s, %(notes)s)
        RETURNING id
    """
    row = {
        "git_commit_sha": None,
        "retrieval_strategy": None,
        "golden_set_size": None,
        "recall_at_5": None,
        "mrr": None,
        "citation_accuracy": None,
        "temporal_correctness": None,
        "refusal_correctness": None,
        "faithfulness": None,
        "answer_relevancy": None,
        "raw_results_path": None,
        "notes": None,
        **rec,
    }
    with conn.cursor() as cur:
        cur.execute(sql, row)
        return str(cur.fetchone()[0])


def latest_eval_run(conn: psycopg.Connection) -> dict | None:
    """Most recent eval run, for GET /api/eval/latest."""
    sql = """
        SELECT id, git_commit_sha, run_at, retrieval_strategy, golden_set_size,
               recall_at_5, mrr, citation_accuracy, temporal_correctness,
               refusal_correctness, faithfulness, answer_relevancy, notes
        FROM eval_runs ORDER BY run_at DESC LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        if not row:
            return None
        cols = [c.name for c in cur.description]
        out = dict(zip(cols, row))
        out["id"] = str(out["id"])
        out["run_at"] = out["run_at"].isoformat() if out["run_at"] else None
        return out


def list_documents(conn: psycopg.Connection) -> list[dict]:
    """Return all documents (id, number, title, status) for pickers/lookup."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, doc_number, title, status FROM documents ORDER BY doc_number"
        )
        return [
            {"id": str(r[0]), "doc_number": r[1], "title": r[2], "status": r[3]}
            for r in cur.fetchall()
        ]


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
