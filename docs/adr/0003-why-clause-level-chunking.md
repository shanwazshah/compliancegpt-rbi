# ADR 0003 — Structure-aware, sentence-packed chunking with parent links

- Status: Accepted
- Date: 2026-07-16

## Context

Legal/regulatory text doesn't split cleanly at fixed character boundaries. Naive
splitting cuts mid-clause and produces incoherent chunks that retrieve poorly.

## Decision

Chunk **structure-aware**: split on real structural headings (Chapter / Part /
Annexure / Schedule) into section-level **parent** chunks, then pack each
section's body into ~400–600-token **child** chunks along sentence boundaries,
with a word-window fallback for oversized sentences. Children link to their
parent (`parent_index`) for later small-to-big expansion.

## Rationale

- Two failed extremes informed this (see git history): treating every numbered
  clause as a heading shattered a document into 100+ tiny chunks; treating whole
  chapters as one paragraph produced 2000-token blobs. Sentence-level packing
  gave a stable ~412-token average, max 598 (`evals`/chunking output).
- pdfplumber output has single newlines, not blank-line paragraph breaks — so
  packing had to work at the sentence level, not the paragraph level.

## Consequences

- Retrieval operates on precise child chunks; parent expansion (pull the fuller
  section) is available via `parent_index` as a later enhancement.
- Chunking is a known iteration point (spec §19) — the heuristics are tuned for
  RBI Master Directions and would need revisiting for other document families.
