# ADR 0004 — Temporal correctness via a supersession graph, not a status flag

- Status: Accepted
- Date: 2026-07-16

## Context

The project's signature requirement is answering "what was the rule *as of a past
date*", not just "what is the rule now". The 28 Nov 2025 RBI consolidation
replaced ~9,445 circulars with 244 Master Directions, so the same topic has
different governing documents depending on the date asked about.

## Decision

Model supersession as a **directed graph** (`supersession_edges`: predecessor →
successor, `relation_type`, `effective_date`) and compute the in-force document
set at any reference date with `resolve_temporal_scope`, applied as a
**pre-retrieval filter**.

## Rationale

- A single `status` column ("active"/"superseded") only answers "in force *now*".
  It cannot answer "in force on 2024-06-30", which needs to know *when* each
  supersession took effect — that lives on the edge's `effective_date`.
- A document is in force at date D iff it was issued on/before D **and** no
  predecessor edge from it has an `effective_date` on/before D. This is a graph
  query, not a boolean field.
- Pre-filtering (not post-filtering) is essential: filtering after retrieval lets
  superseded-but-semantically-similar documents crowd the top-k first (spec §11.2).
- Unit-tested against a synthetic before/after pair; verified live (2024 query
  correctly excludes the 2025 Master Direction).

## Consequences

- Requires building/curating the graph. We seed one hand-verified edge (2016 KYC
  MD → 2025 NBFC KYC MD); the full "circulars withdrawn" import is future work.
- `extraction_method` on every edge distinguishes ground truth
  (`manual_verified` / `rbi_explicit_list`) from LLM-inferred edges.
