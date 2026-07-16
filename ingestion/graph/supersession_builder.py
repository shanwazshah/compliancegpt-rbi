"""Seed the supersession graph with verified before/after pairs.

The 28 Nov 2025 consolidation withdrew thousands of older circulars/MDs and
folded them into the new Master Directions. The full "Circulars Withdrawn"
import is a large ingestion job (spec Phase 2); here we seed a small set of
hand-verified predecessor→successor edges so the temporal filter has a real
before/after pair to resolve. extraction_method='manual_verified' marks these
as ground truth (higher trust than LLM-inferred edges).

Add more entries to SEED as you verify them.

Run:  python -m ingestion.graph.supersession_builder
"""

from __future__ import annotations

from app.db.queries import get_connection

CONSOLIDATION_DATE = "2025-11-28"

# Each entry: a real pre-consolidation predecessor document, and the current
# (post-consolidation) Master Direction that superseded/consolidated it.
SEED = [
    {
        "predecessor": {
            "doc_number": "RBI/DBR/2015-16/18",
            "title": "Master Direction - Know Your Customer (KYC) Direction, 2016",
            "issue_date": "2016-02-25",
            "source_url": "https://www.rbi.org.in/Scripts/BS_ViewMasDirections.aspx?id=11566",
        },
        "successor_doc_number": "RBI/DOR/2025-26/361",  # NBFC KYC Directions, 2025
        "relation_type": "consolidates",
    },
]


def _doc_id(cur, doc_number: str) -> str | None:
    cur.execute("SELECT id FROM documents WHERE doc_number = %s", (doc_number,))
    row = cur.fetchone()
    return str(row[0]) if row else None


def build() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        for entry in SEED:
            pred = entry["predecessor"]
            # Upsert the historical predecessor (status = superseded).
            cur.execute(
                """
                INSERT INTO documents (source_regulator, doc_type, doc_number, title,
                                       issue_date, status, source_url, entity_categories)
                VALUES ('RBI','master_direction',%(doc_number)s,%(title)s,%(issue_date)s,
                        'superseded',%(source_url)s, ARRAY['NBFC'])
                ON CONFLICT (source_regulator, doc_number) DO UPDATE SET
                    status='superseded', updated_at=now()
                RETURNING id
                """,
                pred,
            )
            pred_id = str(cur.fetchone()[0])
            succ_id = _doc_id(cur, entry["successor_doc_number"])
            if not succ_id:
                print(f"  ! successor {entry['successor_doc_number']} not found — skipping edge")
                continue
            # Insert the edge if it doesn't already exist.
            cur.execute(
                """
                INSERT INTO supersession_edges (predecessor_doc_id, successor_doc_id,
                                                relation_type, effective_date,
                                                extraction_confidence, extraction_method)
                SELECT %s,%s,%s,%s,1.0,'manual_verified'
                WHERE NOT EXISTS (
                    SELECT 1 FROM supersession_edges
                    WHERE predecessor_doc_id=%s AND successor_doc_id=%s
                )
                """,
                (pred_id, succ_id, entry["relation_type"], CONSOLIDATION_DATE, pred_id, succ_id),
            )
            rel = entry["relation_type"]
            print(f"  {pred['doc_number']}  --{rel}-->  {entry['successor_doc_number']}")

        cur.execute("SELECT count(*) FROM supersession_edges")
        print(f"\nsupersession_edges now holds {cur.fetchone()[0]} edge(s)")


if __name__ == "__main__":
    build()
