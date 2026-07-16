"""Detect corpus drift: has RBI published/withdrawn NBFC Master Directions?

Scrapes the live RBI index and compares the set of NBFC MD doc numbers against a
committed snapshot (ingestion/known_documents.json). Deliberately does NOT
download PDFs or touch a database, so it runs cheaply in CI on a schedule.

Exit codes:
    0 = corpus unchanged
    1 = drift detected (new or removed documents) -> CI opens an issue
    2 = scrape failed (RBI unreachable / layout changed) -> also visible, not silent

Regenerate the snapshot after an intentional re-ingest:
    python -m ingestion.check_for_updates --update-snapshot
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SNAPSHOT = Path("ingestion") / "known_documents.json"


def _live_doc_numbers() -> set[str]:
    """Scrape the RBI index and return the NBFC MD doc numbers currently listed."""
    from ingestion.scrapers.rbi_master_directions import (
        INDEX_URL,
        fetch_html,
        list_nbfc_directions,
        parse_detail,
    )

    index_html = fetch_html(INDEX_URL, "md_did401.html", force=True)
    entries = list_nbfc_directions(index_html)
    if not entries:
        raise RuntimeError("index parsed but produced 0 NBFC entries - layout changed?")
    numbers: set[str] = set()
    for _title, url in entries:
        detail_id = url.split("id=")[-1]
        detail_html = fetch_html(url, f"detail_{detail_id}.html", force=True)
        doc_number, _issue_date, _pdf = parse_detail(detail_html)
        if doc_number:
            numbers.add(doc_number)
    return numbers


def _load_snapshot() -> set[str]:
    if not SNAPSHOT.exists():
        return set()
    return set(json.loads(SNAPSHOT.read_text(encoding="utf-8"))["doc_numbers"])


def _write_snapshot(numbers: set[str]) -> None:
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps({"doc_numbers": sorted(numbers)}, indent=2), encoding="utf-8"
    )


def main() -> int:
    update = "--update-snapshot" in sys.argv
    try:
        live = _live_doc_numbers()
    except Exception as exc:
        print(f"::error::scrape FAILED: {type(exc).__name__}: {exc}")
        return 2

    if update:
        _write_snapshot(live)
        print(f"snapshot updated: {len(live)} documents")
        return 0

    known = _load_snapshot()
    added = sorted(live - known)
    removed = sorted(known - live)
    print(f"live={len(live)} known={len(known)} added={len(added)} removed={len(removed)}")
    if added or removed:
        if added:
            print("::warning::NEW documents: " + ", ".join(added))
        if removed:
            print("::warning::REMOVED/withdrawn documents: " + ", ".join(removed))
        return 1
    print("corpus unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
