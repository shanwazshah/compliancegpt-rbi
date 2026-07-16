# ADR 0005 — PDF parser: pdfplumber for the MVP, Docling as an optional upgrade

- Status: Accepted (hardware-constrained)
- Date: 2026-07-16

## Context

The spec's first choice is Docling (layout-aware, reconstructs tables). The dev
machine is RAM- and disk-constrained.

## Decision

Use **pdfplumber** as the default parser; keep Docling as an optional `[docling]`
extra behind the same `parse_pdf()` interface.

## Rationale

- Docling rasterizes every page for its layout/OCR models. On this hardware it
  exhausted RAM (`std::bad_alloc`) on the larger Master Directions — even with OCR
  disabled — and took 315s for a single (failing) document.
- These PDFs are **born-digital** (embedded text), so pdfplumber extracts text
  directly with near-zero memory: all 30 documents parsed in **81 seconds**.
- The tradeoff is weaker table reconstruction; acceptable for an MVP whose goal is
  end-to-end cited answers.

## Consequences

- `parse_pdf()` is a stable seam — swapping back to Docling on a higher-RAM box is
  a config/extra change, nothing downstream changes.
- Complex annexure tables are extracted as linear text, not structured tables;
  Docling is the documented path when that fidelity is needed.
