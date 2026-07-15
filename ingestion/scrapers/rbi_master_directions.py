"""Scraper for RBI NBFC Master Directions (the 28 Nov 2025 consolidation).

Pilot corpus = the ~30 "Reserve Bank of India (Non-Banking Financial Companies
- ...) Directions, 2025" documents listed under the Department of Regulation
consolidation page (did=401).

Scraping etiquette (a deliberate design choice, not just politeness):
  * Browser-like User-Agent  -> RBI's WAF returns HTTP 418 to obvious bots.
  * >= 1 request/second      -> we never hammer the server.
  * On-disk caching          -> a page/PDF already fetched is never re-fetched,
                                which also makes re-runs instant and idempotent.
RBI's robots.txt is itself WAF-blocked (418), so we default to conservative
crawling rather than assuming everything is allowed.

Run:  python -m ingestion.scrapers.rbi_master_directions
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = "https://www.rbi.org.in/Scripts/"
INDEX_URL = BASE + "BS_ViewMasterDirections.aspx?did=401"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

DATA = Path("data")
CACHE = DATA / "cache"          # cached HTML pages
PDF_DIR = DATA / "pdfs"         # downloaded PDFs, named by doc_number
MANIFEST = DATA / "nbfc_manifest.json"

MIN_INTERVAL = 1.0              # seconds between LIVE network requests
_last_request_at = 0.0

# Match e.g. RBI/DOR/2025-26/361
DOC_NUMBER_RE = re.compile(r"RBI/[A-Za-z]+/20\d\d-\d\d/\d+")
DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{1,2},\s+20\d{2}"
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        "January February March April May June July August September "
        "October November December".split(),
        start=1,
    )
}


@dataclass
class MDRecord:
    """One scraped Master Direction."""

    doc_number: str
    title: str
    detail_url: str
    pdf_url: str | None
    issue_date: str | None      # ISO 'YYYY-MM-DD'
    pdf_path: str | None
    raw_text_hash: str | None   # sha256 of the PDF bytes, for idempotent re-ingest


def _throttle() -> None:
    """Ensure at least MIN_INTERVAL seconds between live requests."""
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def _get(url: str) -> httpx.Response:
    _throttle()
    resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=40, follow_redirects=True)
    resp.raise_for_status()
    return resp


def fetch_html(url: str, cache_key: str, *, force: bool = False) -> str:
    """Return page HTML, using the on-disk cache unless force=True."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / cache_key
    if path.exists() and not force:
        return path.read_text(encoding="utf-8")
    resp = _get(url)
    resp.encoding = "utf-8"
    path.write_text(resp.text, encoding="utf-8")
    return resp.text


def list_nbfc_directions(index_html: str) -> list[tuple[str, str]]:
    """From the did=401 index, return (title, detail_url) for each NBFC MD."""
    soup = BeautifulSoup(index_html, "lxml")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "BS_ViewMasDirections.aspx?id=" not in href:
            continue
        title = " ".join(a.get_text(strip=True).split())
        # Pilot domain filter: NBFC Directions only (exclude Housing Finance etc.)
        if "Non-Banking Financial Compan" not in title:
            continue
        url = href if href.startswith("http") else BASE + href.lstrip("/").removeprefix("Scripts/")
        if url in seen:
            continue
        seen.add(url)
        out.append((title, url))
    return out


def parse_detail(detail_html: str) -> tuple[str | None, str | None, str | None]:
    """Extract (doc_number, issue_date_iso, main_pdf_url) from a detail page."""
    soup = BeautifulSoup(detail_html, "lxml")
    text = soup.get_text("\n", strip=True)

    doc_number = None
    issue_date = None
    m = DOC_NUMBER_RE.search(text)
    if m:
        doc_number = m.group()
        # The issue date is the first month-name date shortly after the ref number.
        window = text[m.end() : m.end() + 800]
        d = DATE_RE.search(window)
        if d:
            month = d.group(1)
            day = int(d.group(0).split()[1].rstrip(","))
            year = int(d.group(0)[-4:])
            issue_date = f"{year:04d}-{_MONTHS[month]:02d}-{day:02d}"

    # Main PDF = the notification PDF (annexures live under /content/pdfs/*_A#.pdf).
    pdf_url = None
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/notification/PDFs/" in href and href.lower().endswith(".pdf"):
            pdf_url = href
            break
    return doc_number, issue_date, pdf_url


def download_pdf(pdf_url: str, doc_number: str) -> tuple[str, str]:
    """Download a PDF (skip if present); return (path, sha256_hash)."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", doc_number)
    path = PDF_DIR / f"{safe}.pdf"
    if path.exists():
        data = path.read_bytes()
    else:
        data = _get(pdf_url).content
        path.write_bytes(data)
    return str(path), hashlib.sha256(data).hexdigest()


def scrape(limit: int | None = None) -> list[MDRecord]:
    """Full scrape: index -> detail pages -> PDFs -> manifest."""
    index_html = fetch_html(INDEX_URL, "md_did401.html")
    entries = list_nbfc_directions(index_html)
    if limit:
        entries = entries[:limit]
    print(f"Found {len(entries)} NBFC Master Directions to scrape.")

    records: list[MDRecord] = []
    for i, (title, url) in enumerate(entries, 1):
        detail_id = url.split("id=")[-1]
        detail_html = fetch_html(url, f"detail_{detail_id}.html")
        doc_number, issue_date, pdf_url = parse_detail(detail_html)
        pdf_path = pdf_hash = None
        if doc_number and pdf_url:
            pdf_path, pdf_hash = download_pdf(pdf_url, doc_number)
        rec = MDRecord(
            doc_number=doc_number or f"UNKNOWN-{detail_id}",
            title=title,
            detail_url=url,
            pdf_url=pdf_url,
            issue_date=issue_date,
            pdf_path=pdf_path,
            raw_text_hash=pdf_hash,
        )
        records.append(rec)
        print(f"  [{i}/{len(entries)}] {rec.doc_number}  {'PDF ok' if pdf_path else 'NO PDF'}")

    DATA.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps([asdict(r) for r in records], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nWrote manifest: {MANIFEST}  ({len(records)} records)")
    return records


if __name__ == "__main__":
    scrape()
