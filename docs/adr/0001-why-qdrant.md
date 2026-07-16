# ADR 0001 — Vector store: Qdrant

- Status: Accepted
- Date: 2026-07-15

## Context

The system needs semantic (dense-vector) search over regulatory chunks, and —
critically — a **metadata pre-filter** so the temporal layer can restrict search
to the set of documents in force at a given date *before* similarity ranking.

## Decision

Use **Qdrant** as the vector store, run via Docker Compose alongside Postgres.

## Rationale

- **First-class payload filtering.** Qdrant filters on payload fields (e.g.
  `doc_number`) as part of the search, which is exactly what the temporal
  pre-filter needs — `dense_search(..., allowed_doc_numbers=...)` compiles to a
  Qdrant `Filter`. Post-retrieval filtering would let superseded-but-similar docs
  crowd the top-k first (spec §11.2).
- **Self-hostable, one-command local run** via Docker — no cloud dependency for
  a portfolio project.
- **Simple client**, cosine distance on normalized vectors.

## Alternatives considered

- **pgvector** (vectors inside Postgres): one fewer service, but weaker
  filtering ergonomics and less headroom for scaling the vector workload.
- **FAISS** (in-process): fast, but no server, no payload filtering, no
  persistence story out of the box.

## Consequences

- Two data services to run (Postgres + Qdrant), reflected in `docker-compose.yml`.
- Chunk text is stored in the Qdrant payload, so BM25 can build its index by
  scrolling the collection (no separate text store needed at MVP scale).
