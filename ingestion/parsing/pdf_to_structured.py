"""PDF -> structured Markdown, using Docling (layout-aware, table-preserving).

Why Markdown? It keeps the document's *structure* — headings stay headings,
tables stay tables (as Markdown tables) — which we rely on later for
structure-aware chunking. Plain text extraction would flatten all of that.

Parsed output is cached to data/parsed/<doc>.md so we never re-parse an
unchanged PDF (parsing is the slow step, so caching matters a lot).

Run (parse everything in the manifest):
    python -m ingestion.parsing.pdf_to_structured
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path("data")
MANIFEST = DATA / "nbfc_manifest.json"
PARSED_DIR = DATA / "parsed"

# Lazily created so importing this module is cheap (Docling is heavy to import).
_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from docling.document_converter import DocumentConverter

        _converter = DocumentConverter()
    return _converter


def parse_pdf(pdf_path: str | Path, *, force: bool = False) -> str:
    """Return the PDF as structured Markdown, using the on-disk cache."""
    pdf_path = Path(pdf_path)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PARSED_DIR / (pdf_path.stem + ".md")
    if out.exists() and not force:
        return out.read_text(encoding="utf-8")

    result = _get_converter().convert(str(pdf_path))
    markdown = result.document.export_to_markdown()
    out.write_text(markdown, encoding="utf-8")
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
