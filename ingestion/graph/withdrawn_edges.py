"""Turn RBI's published withdrawal list into documents + supersession edges.

This is the bulk counterpart to `supersession_builder.build()`'s hand-verified
seed. It reads `data/withdrawn_manifest.json` (see
`ingestion.scrapers.rbi_circulars_withdrawn`) and writes two *separate* kinds of
claim, because they do not deserve the same trust:

1. **The withdrawal itself — ground truth.** RBI publishes that a circular was
   withdrawn. We record that on the document (`status='superseded'`,
   `withdrawn_date`). The temporal filter can retire a circular on this fact
   alone, with no successor needed.

2. **Which Master Direction replaced it — inferred.** RBI's list does not say.
   We infer it by matching the circular's title against the topic of each 2025
   NBFC Master Direction, and store the match score as `extraction_confidence`
   with `extraction_method='title_match'`. Low-scoring pairs get **no edge** —
   an unmatched circular is still correctly retired by (1), so there is no
   incentive to invent a link.

Spec §19 warns that cross-reference extraction will have false positives; keeping
the confident fact and the inferred fact in different columns is how a reader
(or an interviewer) can tell which is which.

Run:  python -m ingestion.graph.withdrawn_edges --dry-run   # report, no writes
      python -m ingestion.graph.withdrawn_edges
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from app.db.queries import get_connection
from ingestion.graph.supersession_builder import CONSOLIDATION_DATE

MANIFEST = Path("data") / "withdrawn_manifest.json"

# A title match must clear this to become an edge. Tuned on the pilot corpus:
# high enough that "Credit Cards" does not attach to "Credit Facilities", low
# enough that real topical matches survive wording drift between 2016 and 2025.
MIN_MATCH_SCORE = 0.55

# Words that carry no topical signal in RBI document titles.
STOPWORDS = frozenset(
    """
    a an the and or of for to in on by with as at from is are be shall
    master direction directions circular circulars guidelines guideline
    reserve bank india rbi non banking financial company companies nbfc nbfcs
    amendment amendments updated review revised revision second third
    """.split()
)

# The topic of a 2025 MD is the text inside its parentheses, after the entity
# name: "Reserve Bank of India (Non-Banking Financial Companies – Know Your
# Customer) Directions, 2025" -> "Know Your Customer".
MD_TOPIC = re.compile(r"\(([^)]*)\)")

# Split the entity prefix from the topic. Must NOT be a bare "-" class: the
# entity name itself contains a hyphen ("Non-Banking"), so splitting on any
# hyphen yields "Banking Financial Companies - Know Your Customer".
TOPIC_SEPARATOR = re.compile(r"\s+[–—]\s+|\s+-\s+")


@dataclass
class Match:
    """A proposed predecessor -> successor link."""

    doc_number: str
    title: str
    successor_doc_number: str | None
    successor_title: str | None
    score: float


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def md_topic_text(md_title: str) -> str:
    """The topic phrase of a 2025 MD title, entity prefix removed.

    "Reserve Bank of India (Non-Banking Financial Companies – Know Your Customer)
    Directions, 2025"  ->  "Know Your Customer"
    """
    inner = MD_TOPIC.findall(md_title)
    # Prefer the entity-qualified group ("Non-Banking Financial Companies - X");
    # fall back to the whole title if the format ever changes.
    topic = max(inner, key=len) if inner else md_title
    parts = TOPIC_SEPARATOR.split(topic, maxsplit=1)
    return " ".join(parts[-1].split()).strip().rstrip(",")


def md_topic_tokens(md_title: str) -> set[str]:
    """Topical tokens for a 2025 Master Direction title."""
    return _tokens(md_topic_text(md_title))


def score_match(circular_title: str, md_topic: set[str]) -> float:
    """Fraction of the MD's topic words present in the circular's title.

    Asymmetric on purpose: an MD topic is short and specific ("Know Your
    Customer"), while circular titles are long and noisy. Asking "how much of the
    MD's topic does this circular mention?" is far more discriminating than a
    symmetric overlap, which long titles would dominate.
    """
    if not md_topic:
        return 0.0
    circular = _tokens(circular_title)
    return len(md_topic & circular) / len(md_topic)


def best_successor(circular_title: str, mds: list[tuple[str, str, set[str]]]) -> Match:
    """Pick the highest-scoring Master Direction for one withdrawn circular."""
    best_num = best_title = None
    best_score = 0.0
    for doc_number, title, topic in mds:
        s = score_match(circular_title, topic)
        if s > best_score:
            best_num, best_title, best_score = doc_number, title, s
    if best_score < MIN_MATCH_SCORE:
        return Match(circular_title, circular_title, None, None, best_score)
    return Match(circular_title, circular_title, best_num, best_title, best_score)


def _load_active_mds(cur) -> list[tuple[str, str, set[str]]]:
    """The 2025 NBFC Master Directions currently in force = candidate successors."""
    cur.execute(
        "SELECT doc_number, title FROM documents WHERE status = 'active' ORDER BY doc_number"
    )
    return [(num, title, md_topic_tokens(title)) for num, title in cur.fetchall()]


def _doc_type(doc_number: str, title: str) -> str:
    lowered = title.lower()
    if "master direction" in lowered:
        return "master_direction"
    if "master circular" in lowered:
        return "master_circular"
    return "circular"


def build(dry_run: bool = False) -> None:
    """Load withdrawn circulars and link them to their successor MDs."""
    if not MANIFEST.exists():
        raise SystemExit(
            f"{MANIFEST} not found — run "
            "`python -m ingestion.scrapers.rbi_circulars_withdrawn` first."
        )
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    print(f"Read {len(records)} withdrawn circulars from {MANIFEST}")

    with get_connection() as conn, conn.cursor() as cur:
        mds = _load_active_mds(cur)
        if not mds:
            raise SystemExit(
                "No active documents to match against — run `python -m "
                "ingestion.load_documents` first."
            )
        print(f"Matching against {len(mds)} active Master Directions.\n")

        matched = unmatched = skipped = 0
        edges_written = 0
        for rec in records:
            issue_date = rec.get("issue_date")
            if not issue_date:
                # documents.issue_date is NOT NULL, and a document with no
                # knowable date cannot participate in a temporal answer anyway.
                skipped += 1
                continue

            m = best_successor(rec["title"], mds)
            if m.successor_doc_number:
                matched += 1
            else:
                unmatched += 1

            if dry_run:
                continue

            # (1) The withdrawal itself — ground truth from RBI's published list.
            cur.execute(
                """
                INSERT INTO documents (source_regulator, doc_type, doc_number, title,
                                       issue_date, status, source_url, entity_categories,
                                       withdrawn_date, issue_date_precision)
                VALUES ('RBI', %(doc_type)s, %(doc_number)s, %(title)s, %(issue_date)s,
                        'superseded', %(source_url)s, ARRAY['NBFC'],
                        %(withdrawn_date)s, %(precision)s)
                ON CONFLICT (source_regulator, doc_number) DO UPDATE SET
                    title                = EXCLUDED.title,
                    issue_date           = EXCLUDED.issue_date,
                    status               = 'superseded',
                    withdrawn_date       = EXCLUDED.withdrawn_date,
                    issue_date_precision = EXCLUDED.issue_date_precision,
                    updated_at           = now()
                RETURNING id
                """,
                {
                    "doc_type": _doc_type(rec["doc_number"], rec["title"]),
                    "doc_number": rec["doc_number"],
                    "title": rec["title"],
                    "issue_date": issue_date,
                    "source_url": rec.get("detail_url") or "https://www.rbi.org.in/scripts/"
                    "NotificationUserWithdrawnCircular.aspx",
                    "withdrawn_date": CONSOLIDATION_DATE,
                    "precision": rec.get("date_source") or "listing_fallback",
                },
            )
            pred_id = str(cur.fetchone()[0])

            # (2) The successor link — inferred, and only when confident.
            if not m.successor_doc_number:
                continue
            cur.execute(
                "SELECT id FROM documents WHERE doc_number = %s", (m.successor_doc_number,)
            )
            row = cur.fetchone()
            if not row:
                continue
            succ_id = str(row[0])
            cur.execute(
                """
                INSERT INTO supersession_edges (predecessor_doc_id, successor_doc_id,
                                                relation_type, effective_date,
                                                extraction_confidence, extraction_method)
                SELECT %s, %s, 'consolidates', %s, %s, 'title_match'
                WHERE NOT EXISTS (
                    SELECT 1 FROM supersession_edges
                    WHERE predecessor_doc_id = %s AND successor_doc_id = %s
                )
                """,
                (pred_id, succ_id, CONSOLIDATION_DATE, round(m.score, 3), pred_id, succ_id),
            )
            edges_written += cur.rowcount

        print(f"  linked to a successor MD : {matched}")
        print(f"  withdrawn, no confident successor : {unmatched}")
        print(f"  skipped (no issue date)  : {skipped}")
        if dry_run:
            print("\n(dry run — nothing written)")
            return
        print(f"  new edges written        : {edges_written}")

        cur.execute("SELECT count(*) FROM supersession_edges")
        print(f"\nsupersession_edges now holds {cur.fetchone()[0]} edge(s)")
        cur.execute("SELECT status, count(*) FROM documents GROUP BY status ORDER BY status")
        for status, n in cur.fetchall():
            print(f"  documents[{status}] = {n}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report matches without writing")
    args = ap.parse_args(argv)
    build(dry_run=args.dry_run)


if __name__ == "__main__":
    main(sys.argv[1:])
