"""Unit tests for temporal scope resolution (the supersession-graph filter).

Seeds a synthetic before/after pair mirroring the Nov 2025 consolidation:
  OLD doc issued 2016, SUPERSEDED (edge effective 2025-11-28) by NEW doc.
Then checks the in-force set at three reference dates.

Requires Postgres running (docker compose up). The fixture cleans up after itself.
"""

from datetime import date

import pytest

from app.db.queries import get_connection
from app.retrieval.temporal_filter import in_force_doc_numbers

OLD = "TEST/OLD/KYC-2016"
NEW = "TEST/NEW/KYC-2025"
EFFECTIVE = date(2025, 11, 28)  # the real consolidation date


def _cleanup(cur) -> None:
    """Delete edges first (FK), then the test documents. Idempotent."""
    cur.execute(
        """
        DELETE FROM supersession_edges
        WHERE predecessor_doc_id IN (SELECT id FROM documents WHERE doc_number IN (%s,%s))
           OR successor_doc_id   IN (SELECT id FROM documents WHERE doc_number IN (%s,%s))
        """,
        (OLD, NEW, OLD, NEW),
    )
    cur.execute("DELETE FROM documents WHERE doc_number IN (%s,%s)", (OLD, NEW))


@pytest.fixture()
def seeded_pair():
    """Insert OLD --superseded by--> NEW, yield, then delete."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            _cleanup(cur)  # clear any leftovers from a prior failed run
            cur.execute(
                """
                INSERT INTO documents (source_regulator, doc_type, doc_number, title,
                                       issue_date, status, source_url)
                VALUES ('RBI','master_direction',%s,'Old KYC MD (2016)','2016-02-25',
                        'superseded','http://example/old')
                RETURNING id
                """,
                (OLD,),
            )
            old_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO documents (source_regulator, doc_type, doc_number, title,
                                       issue_date, status, source_url)
                VALUES ('RBI','master_direction',%s,'New KYC MD (2025)',%s,
                        'active','http://example/new')
                RETURNING id
                """,
                (NEW, EFFECTIVE),
            )
            new_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO supersession_edges (predecessor_doc_id, successor_doc_id,
                                                relation_type, effective_date, extraction_method)
                VALUES (%s,%s,'consolidates',%s,'manual_verified')
                """,
                (old_id, new_id, EFFECTIVE),
            )
    yield
    with get_connection() as conn, conn.cursor() as cur:
        _cleanup(cur)


def _in_force(ref: date) -> set[str]:
    with get_connection() as conn:
        return in_force_doc_numbers(conn, ref)


def test_before_either_existed(seeded_pair):
    got = _in_force(date(2015, 1, 1))
    assert OLD not in got and NEW not in got


def test_as_of_2024_old_is_in_force_new_is_not(seeded_pair):
    """The adversarial case: in 2024 the OLD rule applied, not the 2025 MD."""
    got = _in_force(date(2024, 6, 30))
    assert OLD in got
    assert NEW not in got


def test_today_new_is_in_force_old_is_superseded(seeded_pair):
    got = _in_force(date(2026, 7, 16))
    assert NEW in got
    assert OLD not in got
