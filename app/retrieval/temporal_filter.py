"""Temporal scope resolution — the project's signature capability.

Given a reference date, compute which documents were *in force* at that date,
using the documents table + the supersession graph. This runs as a PRE-retrieval
filter (spec §11.2): we restrict the searchable set to in-force documents before
similarity search, so a superseded-but-similar document can never crowd the top-k.

A document is IN FORCE at `reference_date` when:
  1. it was issued on or before `reference_date`, AND
  2. it has NOT been superseded by an edge whose effective_date is on or before
     `reference_date` (no predecessor edge has kicked in yet).
"""

from __future__ import annotations

from datetime import date

import psycopg


def in_force_document_ids(conn: psycopg.Connection, reference_date: date) -> set[str]:
    """Return the set of document UUIDs in force at reference_date."""
    sql = """
        SELECT d.id
        FROM documents d
        WHERE d.issue_date <= %(ref)s
          AND NOT EXISTS (
              SELECT 1
              FROM supersession_edges e
              WHERE e.predecessor_doc_id = d.id
                AND e.effective_date IS NOT NULL
                AND e.effective_date <= %(ref)s
          )
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"ref": reference_date})
        return {str(row[0]) for row in cur.fetchall()}


def in_force_doc_numbers(conn: psycopg.Connection, reference_date: date) -> set[str]:
    """Same as above but keyed by human-readable doc_number (for Qdrant filtering)."""
    sql = """
        SELECT d.doc_number
        FROM documents d
        WHERE d.issue_date <= %(ref)s
          AND NOT EXISTS (
              SELECT 1
              FROM supersession_edges e
              WHERE e.predecessor_doc_id = d.id
                AND e.effective_date IS NOT NULL
                AND e.effective_date <= %(ref)s
          )
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"ref": reference_date})
        return {row[0] for row in cur.fetchall()}
