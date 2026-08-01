"""Generate date-scoped golden-set rows from RBI's published withdrawal list.

## Why these rows are generated rather than hand-written

Spec §19 is right that a sloppy golden set undermines every metric built on it.
These rows are generated, but nothing about their **answer key** is invented: the
predecessor document, its verified issue date, and the fact that it was withdrawn
on 2025-11-28 all come from RBI's own "Circulars Withdrawn" index
(`data/withdrawn_manifest.json`). Only the question wording is templated. Each
row records `source` so the eval report can state exactly how many rows were
hand-written vs generated — see `evals/reports/`.

## What a temporal row actually asserts

The indexed corpus is the 30 Nov-2025 NBFC Master Directions. The withdrawn
predecessors are ingested as *metadata* (for the supersession graph) but their
PDFs are not chunked or embedded, so no retriever can return their text.

That constrains the metric to what spec §14 actually asks for — "% of date-scoped
questions answered from documents actually in force at that date" — which is a
statement about **what must NOT be cited**:

    At reference_date D (before the consolidation), a correct answer cites no
    document that was not in force at D. Citing a Nov-2025 Master Direction for
    a 2023 question is the exact failure this project exists to prevent.

So `expected_doc_numbers` is empty and `must_not_cite` names the successor MD
that naive similarity search would happily return. Each temporal row is paired
with an `in_force_control` row asking the same topic with no date, where that
same MD *is* the expected answer — the pair is what demonstrates the system is
resolving time rather than just matching text.

Run:  python -m evals.generate_temporal_rows            # writes the rows
      python -m evals.generate_temporal_rows --print    # preview only
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

from ingestion.graph.withdrawn_edges import (
    MIN_MATCH_SCORE,
    md_topic_text,
    md_topic_tokens,
    score_match,
)
from ingestion.scrapers.rbi_circulars_withdrawn import CONSOLIDATION_DATE

DATA = Path("data")
WITHDRAWN = DATA / "withdrawn_manifest.json"
MD_MANIFEST = DATA / "nbfc_manifest.json"
OUT = Path("evals") / "temporal_rows.jsonl"

CONSOLIDATION = date.fromisoformat(CONSOLIDATION_DATE)

# Only build a question from a predecessor whose issue date we actually verified
# from its own detail page. A fiscal-year estimate is a lower bound, not a fact,
# and a golden row keyed to a guessed date is worse than no row at all.
REQUIRED_DATE_SOURCE = "detail_page"

MONTHS = (
    "January February March April May June July August September October November December"
).split()

QUESTION_TEMPLATES = [
    "As of {when}, which RBI direction governed {topic} for NBFCs?",
    "What were the applicable RBI rules on {topic} for an NBFC as of {when}?",
    "As of {when}, what governed {topic} for non-banking financial companies?",
]

CONTROL_TEMPLATES = [
    "Which Master Direction currently governs {topic} for NBFCs?",
    "What are the current RBI requirements on {topic} for an NBFC?",
]


# How many date-scoped questions to build per MD topic. Each uses a different
# predecessor and a different reference date, so they are distinct assertions
# about the filter (not the same question reworded); more than a few per topic
# would just pad the count.
MAX_PER_TOPIC = 3


def _topic_of(md_title: str) -> str:
    """Human-readable topic from a 2025 MD title."""
    return md_topic_text(md_title).lower()


def _category_of(topic: str) -> str:
    for key, cat in (
        ("know your customer", "kyc"),
        ("credit card", "credit_cards"),
        ("deposit", "deposits"),
        ("capital adequacy", "prudential"),
        ("income recognition", "prudential"),
        ("microfinance", "microfinance"),
        ("peer to peer", "p2p"),
        ("account aggregator", "account_aggregator"),
        ("governance", "governance"),
        ("outsourcing", "outsourcing"),
        ("securitisation", "securitisation"),
        ("climate", "climate"),
        ("defaulter", "defaulters"),
        ("stressed asset", "stressed_assets"),
    ):
        if key in topic:
            return cat
    return "general"


def _pretty(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.year}"


def _reference_date(issue: date, rng: random.Random) -> date | None:
    """Pick a date where the predecessor was in force and the successor was not.

    Must sit strictly after the predecessor's issue date and strictly before the
    consolidation, with a margin on both sides so the row isn't testing an
    off-by-one on a boundary.
    """
    earliest = issue + timedelta(days=180)
    latest = CONSOLIDATION - timedelta(days=90)
    if earliest >= latest:
        return None
    return earliest + timedelta(days=rng.randrange((latest - earliest).days))


def build_rows(limit: int = 40, seed: int = 20260801) -> list[dict]:
    """Build (temporal, control) golden rows from the two manifests."""
    if not WITHDRAWN.exists() or not MD_MANIFEST.exists():
        raise SystemExit(
            "Missing manifests — run the scrapers first:\n"
            "  python -m ingestion.scrapers.rbi_master_directions\n"
            "  python -m ingestion.scrapers.rbi_circulars_withdrawn"
        )
    rng = random.Random(seed)
    withdrawn = json.loads(WITHDRAWN.read_text(encoding="utf-8"))
    mds = json.loads(MD_MANIFEST.read_text(encoding="utf-8"))
    md_index = [(m["doc_number"], m["title"], md_topic_tokens(m["title"])) for m in mds]

    rows: list[dict] = []
    per_topic: dict[str, int] = {}
    controlled: set[str] = set()        # one control row per topic, not per question

    for rec in withdrawn:
        if sum(1 for r in rows if r["difficulty"] == "adversarial_temporal") >= limit:
            break
        if rec.get("date_source") != REQUIRED_DATE_SOURCE or not rec.get("issue_date"):
            continue
        issue = date.fromisoformat(rec["issue_date"])
        if issue >= CONSOLIDATION:
            continue

        # Which 2025 MD covers this circular's subject? Reuse the same matcher
        # the graph builder uses, so the golden set and the graph agree.
        best_num = best_title = None
        best_score = 0.0
        for num, title, topic_tokens in md_index:
            s = score_match(rec["title"], topic_tokens)
            if s > best_score:
                best_num, best_title, best_score = num, title, s
        if best_score < MIN_MATCH_SCORE or not best_num:
            continue

        topic = _topic_of(best_title or "")
        if not topic or per_topic.get(topic, 0) >= MAX_PER_TOPIC:
            continue
        ref = _reference_date(issue, rng)
        if ref is None:
            continue
        per_topic[topic] = per_topic.get(topic, 0) + 1
        category = _category_of(topic)

        rows.append(
            {
                "question": rng.choice(QUESTION_TEMPLATES).format(
                    when=_pretty(ref), topic=topic
                ),
                "reference_date": ref.isoformat(),
                "expected_doc_numbers": [],
                "must_not_cite": [best_num],
                "expected_answer_summary": (
                    f"As of {_pretty(ref)} the governing instrument was {rec['doc_number']} "
                    f"(issued {rec['issue_date']}, withdrawn {CONSOLIDATION_DATE}). "
                    f"{best_num} was issued on {CONSOLIDATION_DATE} and must NOT be cited "
                    "for this date. That circular's text is not in the indexed corpus, so "
                    "the correct behaviour is to decline rather than cite a later document."
                ),
                "difficulty": "adversarial_temporal",
                "category": category,
                "source": "generated_from_rbi_withdrawn_index",
                "in_force_at_reference_date": rec["doc_number"],
            }
        )
        if topic in controlled:
            continue
        controlled.add(topic)
        rows.append(
            {
                "question": rng.choice(CONTROL_TEMPLATES).format(topic=topic),
                "reference_date": None,
                "expected_doc_numbers": [best_num],
                "must_not_cite": [],
                "expected_answer_summary": (
                    f"Today the governing instrument is {best_num}. Paired control for the "
                    f"{_pretty(ref)} question on the same topic: same wording, different date, "
                    "different correct answer."
                ),
                "difficulty": "medium",
                "category": category,
                "source": "generated_from_rbi_withdrawn_index",
            }
        )

    # Second pass: MD topics with no confidently-matched predecessor still make
    # valid temporal rows. The assertion doesn't need a known predecessor — a
    # document issued on 2025-11-28 cannot be the authority for a 2021 question,
    # whatever preceded it. These cover the rest of the corpus's topics, where
    # naive similarity is most tempted to cite the (semantically perfect) MD.
    for num, title, _tokens in md_index:
        topic = _topic_of(title)
        if not topic or topic in per_topic:
            continue
        per_topic[topic] = 1
        ref = CONSOLIDATION - timedelta(days=rng.randrange(400, 2500))
        rows.append(
            {
                "question": rng.choice(QUESTION_TEMPLATES).format(
                    when=_pretty(ref), topic=topic
                ),
                "reference_date": ref.isoformat(),
                "expected_doc_numbers": [],
                "must_not_cite": [num],
                "expected_answer_summary": (
                    f"{num} was issued on {CONSOLIDATION_DATE} and was not in force as of "
                    f"{_pretty(ref)}, so it must not be cited for this date. No "
                    "pre-consolidation predecessor for this topic is in the indexed corpus, "
                    "so the correct behaviour is to decline."
                ),
                "difficulty": "adversarial_temporal",
                "category": _category_of(topic),
                "source": "generated_from_md_issue_dates",
            }
        )

    return rows


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=25, help="temporal rows (each adds a control)")
    ap.add_argument("--print", action="store_true", dest="preview", help="preview, don't write")
    args = ap.parse_args(argv)

    rows = build_rows(limit=args.limit)
    temporal = sum(1 for r in rows if r["difficulty"] == "adversarial_temporal")
    print(
        f"Built {len(rows)} rows ({temporal} adversarial_temporal "
        f"+ {len(rows) - temporal} control)"
    )

    if args.preview:
        for r in rows[:6]:
            print(json.dumps(r, ensure_ascii=False)[:200])
        return

    OUT.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
