"""Scraper for RBI's official "Circulars Withdrawn" index (spec §5, §10.5).

This page is the **ground truth** for the supersession graph: RBI itself publishes
which circulars it has withdrawn, so edges built from it are `rbi_explicit_list`
rather than LLM-inferred guesswork.

The page carries three separate lists; we key off the header row rather than a
table index, because a positional index silently breaks when RBI adds a section:

  * "Circular Number | Circular Name/Title | Date"  -> Department of Regulation
    (the ~9.4k-row Nov-2025 consolidation list — our pilot domain lives here)
  * "Circular Number | Subject | Date"              -> Department of Supervision
  * a 3-column RRA 2.0 list                         -> ignored (no circular numbers)

## The date trap (why this module fetches detail pages at all)

The listing's `Date` column is the circular's **last-updated** date, NOT its issue
date — the titles admit it themselves ("... Directions, 2016 (Updated as on
27-02-2025)"). Treating it as an issue date would silently corrupt every temporal
metric this project reports, because a 2016 Master Direction would look like a
2025 one and appear "in force" for reference dates it was never in force for.

So each row's true issue date is read from its own detail page where a link
exists, and every record carries `date_source` so downstream code (and the eval
report) can tell verified dates apart from fallbacks. This distinction is the
whole reason the temporal metric is trustworthy.

Scraping etiquette is inherited from `rbi_master_directions` (browser UA, >=1
req/sec, on-disk cache) — we import those helpers rather than re-implementing.

Run:  python -m ingestion.scrapers.rbi_circulars_withdrawn            # NBFC only
      python -m ingestion.scrapers.rbi_circulars_withdrawn --all      # every row
      python -m ingestion.scrapers.rbi_circulars_withdrawn --limit 20 # smoke test
      python -m ingestion.scrapers.rbi_circulars_withdrawn --no-dates # skip fetches
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup

from ingestion.scrapers.rbi_master_directions import (
    _MONTHS,
    DATA,
    DATE_RE,
    fetch_html,
)

WITHDRAWN_URL = "https://www.rbi.org.in/scripts/NotificationUserWithdrawnCircular.aspx"
MANIFEST = DATA / "withdrawn_manifest.json"

# The DoR repeal circular referenced by every 2025 Master Direction's repeal
# chapter ("...stand repealed, as communicated vide circular DOR.RRC.REC.302/
# 33-01-010/2025-26 dated November 28, 2025"). That date is the edge's
# effective_date — the moment the old rules stopped being in force.
REPEAL_CIRCULAR = "DOR.RRC.REC.302/33-01-010/2025-26"
CONSOLIDATION_DATE = "2025-11-28"

# Pilot domain = NBFC (spec §5). Matched against circular number OR title.
NBFC_HINTS = re.compile(
    r"\b(?:DNBR|DNBS|DNBD|NBFC)\b"
    r"|non-banking\s+financial"
    r"|core\s+investment\s+compan"
    r"|peer\s+to\s+peer\s+lending"
    r"|account\s+aggregator"
    r"|standalone\s+primary\s+dealer"
    r"|mortgage\s+guarantee\s+compan"
    r"|housing\s+finance\s+compan"
    r"|asset\s+reconstruction\s+compan",
    re.I,
)

# "Master Direction - ... , 2016 (Updated as on 27-02-2025)" -> drop the suffix,
# which is listing metadata rather than part of the document's real title.
UPDATED_SUFFIX = re.compile(r"\s*\((?:updated|last updated)[^)]*\)\s*$", re.I)

# Fiscal-year suffix in a circular number, e.g. ".../03.10.119/2016-17".
FISCAL_YEAR = re.compile(r"/((?:19|20)\d{2})-(\d{2})(?:\b|$)")


@dataclass
class WithdrawnRecord:
    """One withdrawn circular, as published by RBI."""

    doc_number: str
    title: str
    listing_date: str | None     # the page's "Date" column = LAST-UPDATED, not issue
    detail_url: str | None
    issue_date: str | None       # ISO 'YYYY-MM-DD'
    date_source: str             # 'detail_page' | 'fiscal_year_estimate' | 'unknown'
    department: str              # 'DoR' | 'DoS'


def _cell_text(cell) -> str:
    return " ".join(cell.get_text(" ", strip=True).split())


def _classify_table(table) -> str | None:
    """Return 'DoR' / 'DoS' for the two withdrawn-circular tables, else None.

    Keyed off the header row so that a new section on the page can't silently
    shift a positional index and make us ingest the wrong list.
    """
    first = table.find("tr")
    if not first:
        return None
    headers = [_cell_text(c).lower() for c in first.find_all(["td", "th"])]
    if not any("circular number" in h for h in headers):
        return None
    if any("name/title" in h for h in headers):
        return "DoR"
    if any(h == "subject" or h.startswith("subject") for h in headers):
        return "DoS"
    return None


def _to_iso(match: re.Match[str]) -> str:
    """Convert a DATE_RE match ('August 25, 2016') to ISO ('2016-08-25')."""
    month = match.group(1)
    day = match.group(0).split()[1].rstrip(",")
    year = match.group(0)[-4:]
    return f"{int(year):04d}-{_MONTHS[month]:02d}-{int(day):02d}"


def _iso_date(text: str) -> str | None:
    """Parse the first 'Month DD, YYYY' in `text` to ISO, or None."""
    m = DATE_RE.search(text)
    return _to_iso(m) if m else None


def _loose_pattern(doc_number: str) -> re.Pattern[str]:
    """Regex matching `doc_number` with any punctuation/spacing between tokens."""
    tokens = [t for t in re.split(r"[^A-Za-z0-9]+", doc_number) if t]
    return re.compile(r"[^A-Za-z0-9]*".join(re.escape(t) for t in tokens), re.I)


def issue_date_from_detail(text: str, doc_number: str) -> str | None:
    """Extract a circular's TRUE issue date from its detail-page text.

    RBI pages are laid out as::

        DoR(NBFC).PD.003/03.10.119/2016-17
        August 25, 2016                 <- the issue date
        (Updated as on August 01, 2025) <- amendment stamps, newest first
        (Updated as on May 05, 2025)

    So we anchor on the circular's own number and take the first date after it,
    explicitly skipping "Updated as on" stamps. Taking the first date on the page
    instead would return the most recent amendment (or even today's date from a
    page header) — which is exactly the bug this function exists to avoid.
    """
    idx = text.find(doc_number)
    end = idx + len(doc_number)
    if idx < 0:
        # The listing and the circular itself often punctuate the same number
        # differently -- listing "DNBR.(PD).090/03.10.124/2017-18" vs page
        # "DNBR (PD) 090/03.10.124/2017-18". Match on the alphanumeric run and
        # treat every separator as interchangeable.
        m = _loose_pattern(doc_number).search(text)
        if not m:
            return None
        idx, end = m.start(), m.end()

    window = text[end : end + 400]
    for m in DATE_RE.finditer(window):
        preceding = window[max(0, m.start() - 30) : m.start()]
        if re.search(r"updated\s+as\s+on\s*$", preceding, re.I | re.S):
            continue          # an amendment stamp, not the issue date
        return _to_iso(m)
    return None


def _fiscal_year_estimate(doc_number: str) -> str | None:
    """Approximate issue date from a circular number's fiscal-year suffix.

    RBI's fiscal year starts 1 April, so '2016-17' implies the document was
    issued on/after 2016-04-01. We return that lower bound — deliberately the
    EARLIEST plausible date, so a temporal filter never excludes a document that
    was actually in force. Records using this carry date_source='fiscal_year_estimate'
    so the imprecision is visible rather than laundered into a hard number.
    """
    m = FISCAL_YEAR.search(doc_number)
    return f"{int(m.group(1)):04d}-04-01" if m else None


def parse_withdrawn_rows(html: str) -> list[WithdrawnRecord]:
    """Parse every withdrawn-circular row from the index page."""
    soup = BeautifulSoup(html, "lxml")
    out: list[WithdrawnRecord] = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        dept = _classify_table(table)
        if dept is None:
            continue
        for row in table.find_all("tr")[1:]:       # skip header
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            doc_number = _cell_text(cells[1])
            title = UPDATED_SUFFIX.sub("", _cell_text(cells[2]))
            if not doc_number or not title:
                continue
            # RBI lists some circulars more than once (e.g. amended twice); the
            # document is still one document.
            if doc_number in seen:
                continue
            seen.add(doc_number)

            link = row.find("a", href=True)
            out.append(
                WithdrawnRecord(
                    doc_number=doc_number,
                    title=title,
                    listing_date=_iso_date(_cell_text(cells[3])),
                    detail_url=link["href"] if link else None,
                    issue_date=None,
                    date_source="unknown",
                    department=dept,
                )
            )
    return out


def is_nbfc_relevant(rec: WithdrawnRecord) -> bool:
    """Pilot-domain filter: does this circular concern NBFCs?"""
    return bool(NBFC_HINTS.search(rec.doc_number) or NBFC_HINTS.search(rec.title))


def resolve_issue_date(rec: WithdrawnRecord) -> WithdrawnRecord:
    """Fill in `issue_date` from the circular's own detail page when possible.

    Falls back to a fiscal-year lower bound, and records which was used. Network
    failures degrade to the estimate rather than aborting the whole import.
    """
    if rec.detail_url:
        key = re.sub(r"[^A-Za-z0-9]", "_", rec.detail_url)[-80:]
        try:
            html = fetch_html(rec.detail_url, f"withdrawn_{key}.html")
            text = BeautifulSoup(html, "lxml").get_text("\n", strip=True)
            iso = issue_date_from_detail(text, rec.doc_number)
            if iso:
                rec.issue_date = iso
                rec.date_source = "detail_page"
                return rec
        except Exception as exc:       # noqa: BLE001 - one bad page must not kill the run
            print(f"    ! {rec.doc_number}: detail fetch failed ({type(exc).__name__})")

    est = _fiscal_year_estimate(rec.doc_number)
    if est:
        rec.issue_date = est
        rec.date_source = "fiscal_year_estimate"
    return rec


def scrape(
    *,
    nbfc_only: bool = True,
    limit: int | None = None,
    resolve_dates: bool = True,
) -> list[WithdrawnRecord]:
    """Scrape the withdrawn-circulars index into a manifest."""
    html = fetch_html(WITHDRAWN_URL, "withdrawn_index.html")
    records = parse_withdrawn_rows(html)
    print(f"Parsed {len(records)} unique withdrawn circulars from the index.")

    if nbfc_only:
        records = [r for r in records if is_nbfc_relevant(r)]
        print(f"  -> {len(records)} are NBFC-relevant (pilot domain).")
    if limit:
        records = records[:limit]

    if resolve_dates:
        print(f"Resolving true issue dates for {len(records)} circulars (>=1s apart)...")
        for i, rec in enumerate(records, 1):
            resolve_issue_date(rec)
            if i % 25 == 0 or i == len(records):
                print(f"  [{i}/{len(records)}] resolved")

    by_source: dict[str, int] = {}
    for r in records:
        by_source[r.date_source] = by_source.get(r.date_source, 0) + 1

    DATA.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote manifest: {MANIFEST}  ({len(records)} records)")
    print(f"Issue-date provenance: {by_source}")
    return records


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="keep every department, not just NBFC")
    ap.add_argument("--limit", type=int, default=None, help="cap rows (smoke test)")
    ap.add_argument(
        "--no-dates",
        action="store_true",
        help="skip detail-page fetches (fast, but issue dates stay estimates)",
    )
    args = ap.parse_args(argv)
    scrape(nbfc_only=not args.all, limit=args.limit, resolve_dates=not args.no_dates)


if __name__ == "__main__":
    main(sys.argv[1:])
