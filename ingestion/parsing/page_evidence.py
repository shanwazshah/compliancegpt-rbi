"""Hash-addressed PDF snapshots and physical-page text extraction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pdfplumber

PARSER_VERSION = "pdfplumber-pages-v1"


def snapshot_pdf(path: Path, storage: Path) -> tuple[str, Path, list[dict]]:
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    directory = storage / digest
    directory.mkdir(parents=True, exist_ok=True)
    snapshot = directory / "source.pdf"
    if snapshot.exists():
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != digest:
            raise ValueError("Stored PDF failed its content-hash check")
    else:
        # Exclusive create prevents overwriting immutable snapshots.
        try:
            with snapshot.open("xb") as file:
                file.write(blob)
        except FileExistsError:
            if snapshot.read_bytes() != blob:
                raise ValueError("Concurrent PDF snapshot differs") from None
    cached = directory / f"{PARSER_VERSION}.json"
    if cached.exists():
        pages = json.loads(cached.read_text(encoding="utf-8"))
    else:
        with pdfplumber.open(snapshot) as pdf:
            pages = [
                {
                    "page_number": index,
                    "printed_label": None,  # do not confuse physical pages with printed labels
                    "text": page.extract_text(layout=False) or "",
                }
                for index, page in enumerate(pdf.pages, 1)
            ]
        for page in pages:
            page["text_hash"] = hashlib.sha256(page["text"].encode()).hexdigest()
        # Parsing is an ingestion operation; cache publication is atomic.
        import uuid

        temp = cached.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temp.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        temp.replace(cached)
    if not pages or not any(page["text"].strip() for page in pages):
        raise ValueError("PDF has no extracted text; OCR is required before indexing")
    return digest, snapshot, pages
