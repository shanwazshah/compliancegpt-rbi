"""PDF -> structured text.

Parser choice (see PROJECT_SPEC.md §7, §19 "known hard problems"):
  * The spec's first choice is Docling (layout-aware, reconstructs tables).
  * On this hardware Docling's page-rasterization step exhausts RAM
    (std::bad_alloc) on the larger Master Directions, even with OCR disabled.
  * So the MVP uses **pdfplumber**, which reads embedded text directly (no page
    rendering) — near-zero memory, fast, reliable for born-digital PDFs. The
    tradeoff is weaker table reconstruction; Docling remains the documented
    upgrade for a higher-RAM machine.

We still emit lightweight Markdown structure: detected section headings become
`##` headings so the structure-aware chunker can split along them.

Output is cached to data/parsed/<doc>.md so we never re-parse an unchanged PDF.

Run:  python -m ingestion.parsing.pdf_to_structured
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pdfplumber

DATA = Path("data")
MANIFEST = DATA / "nbfc_manifest.json"
PARSED_DIR = DATA / "parsed"

# Heading heuristics tuned for RBI Master Directions. Only STRUCTURAL markers
# (Chapter/Part/Annexure/Schedule) start a new section — deliberately NOT every
# numbered clause ("2.", "3."), which would shatter a chapter into dozens of
# tiny one-line chunks and hurt retrieval. Numbered clauses stay inside their
# chapter and get packed into ~500-token chunks by the chunker.
_HEADING_RE = re.compile(
    r"^(chapter\s+[ivxlcm]+\b"
    r"|part\s+[ivxlcm]+\b"
    r"|annex(ure)?\b"
    r"|schedule\b)",
    re.IGNORECASE,
)


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    return bool(line) and len(line) <= 120 and bool(_HEADING_RE.match(line))


def parse_pdf(pdf_path: str | Path, *, force: bool = False) -> str:
    """Return the PDF as lightly-structured Markdown, using the on-disk cache."""
    pdf_path = Path(pdf_path)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PARSED_DIR / (pdf_path.stem + ".md")
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    signature = out.with_suffix(".sha256")
    if out.exists() and signature.exists() and signature.read_text() == digest and not force:
        return out.read_text(encoding="utf-8")

    lines: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.split("\n"):
                if _looks_like_heading(raw):
                    lines.append("")  # blank line -> new paragraph before heading
                    lines.append(f"## {raw.strip()}")
                    lines.append("")
                else:
                    lines.append(raw)

    markdown = "\n".join(lines).strip()
    out.write_text(markdown, encoding="utf-8")
    signature.write_text(digest)
    return markdown


def parse_all() -> None:
    """Parse every PDF referenced in the manifest."""
    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    total = len(records)
    for i, rec in enumerate(records, 1):
        pdf_path = rec.get("pdf_path")
        if not pdf_path or not Path(pdf_path).exists():
            print(f"  [{i}/{total}] {rec['doc_number']}  SKIP (no PDF)")
            continue
        md = parse_pdf(pdf_path)
        print(f"  [{i}/{total}] {rec['doc_number']}  parsed -> {len(md):,} chars")


if __name__ == "__main__":
    parse_all()
