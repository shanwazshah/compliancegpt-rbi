# Architecture

How ComplianceGPT is put together, and why. For the full build specification see
[PROJECT_SPEC.md](PROJECT_SPEC.md); for individual decisions see [adr/](adr/).

## Two planes

```
  INGESTION PLANE (batch, scheduled)          SERVING PLANE (online, stateless)
  ────────────────────────────────────        ────────────────────────────────────
  rbi_master_directions.py                    FastAPI  /api/query
    scrape index → detail → PDF                 │
        │                                       ▼
  rbi_circulars_withdrawn.py                  LangGraph agent
    RBI's published withdrawal list             classify
        │  (574 NBFC circulars,                   │  in-scope?  ──no──▶ refuse
        │   426 verified issue dates)             ▼
        ▼                                       resolve_temporal ──┐
  load_documents / withdrawn_edges               │                 │ Postgres:
    documents + supersession_edges               ▼                 │ documents +
        │                                      retrieve ◀──────────┘ supersession_edges
  pdf_to_structured (pdfplumber)                 │  (filtered to in-force doc set)
        │                                        ▼
  chunking → embed_and_upsert                  expand  (parent window)
        │                                        ▼
        ▼                                      generate  (citation-enforcing prompt)
  Qdrant: vectors + payload                      ▼
                                               verify_citations
                                                 ▼
                                               groundedness ──below threshold──▶ low-confidence
                                                 ▼
                                               respond
```

The split is the point: a scheduled **ingestion plane** keeps the corpus current,
and a stateless **serving plane** answers queries. Most portfolio RAG projects
build only the second half, which is why they cannot answer "what happens when
the regulator publishes something new."

## The temporal filter (the part that matters)

Naive RAG retrieves by similarity, so a superseded circular that is semantically
perfect wins the top-k and gets cited. This system resolves *time before
similarity*:

1. `resolve_temporal` computes the set of documents in force at the reference
   date, from `documents` + `supersession_edges` in Postgres.
2. That set is passed into retrieval as a **pre-filter** — Qdrant only searches
   within it.

Filtering after retrieval would be too late: superseded-but-similar documents
would already have crowded out the correct ones.

A document is in force at date *D* when it was issued on or before *D*, was not
withdrawn on or before *D*, and has no supersession edge that took effect on or
before *D*. See [`app/retrieval/temporal_filter.py`](../app/retrieval/temporal_filter.py).

### Two kinds of claim, kept apart

The supersession data encodes two facts with very different reliability, and the
schema keeps them separate on purpose:

| Claim | Source | Stored as | Trust |
|---|---|---|---|
| This circular was withdrawn | RBI's published "Circulars Withdrawn" index | `documents.withdrawn_date` | ground truth |
| *This* Master Direction replaced it | title/topic matching | `supersession_edges` + `extraction_confidence` | inferred |

This matters practically. Early on, the filter could only retire a document via
an edge — so any circular we could not confidently match to a successor stayed
"in force" forever, a false positive in exactly the direction the project exists
to prevent. Recording the withdrawal on the document itself lets the filter
retire a circular on the regulator's authority alone, whether or not we can name
its successor.

Issue-date provenance is tracked the same way (`documents.issue_date_precision`),
because the withdrawal index publishes **last-updated** dates, not issue dates —
a trap that would have silently shifted a 2016 Master Direction into 2025 and
corrupted every temporal number. See
[`ingestion/scrapers/rbi_circulars_withdrawn.py`](../ingestion/scrapers/rbi_circulars_withdrawn.py).

## Data stores

| Store | Holds | Why |
|---|---|---|
| Postgres | documents, supersession_edges, query_logs, eval_runs, query_feedback | relational integrity for the graph; the temporal filter is a SQL query |
| Qdrant | chunk vectors + payload (`doc_number`, `status`, dates) | first-class metadata filtering, which the temporal pre-filter needs ([ADR 0001](adr/0001-why-qdrant.md)) |
| Local disk | cached HTML, PDFs, parsed text | re-runs are instant and idempotent; the scraper never re-fetches unchanged files |

Chunk *text* lives in the Qdrant payload rather than a Postgres `chunks` table —
one store owns the chunk, so the two cannot disagree. Parent-window expansion
reads `parent_text` from the same payload.

## Observability

Every request opens a trace ([`app/observability/tracing.py`](../app/observability/tracing.py))
that records a span per agent node with retrieved candidates and scores. Token
usage and cost are captured at the single LLM entry point
([`app/llm.py`](../app/llm.py)) and accumulated per request via a `ContextVar`, so
one response reports the total cost of every node without threading cost through
the graph state.

Langfuse export is optional. In-process tracing always runs, so the latency
numbers the project reports never depend on an external service being reachable —
and an observability backend can never take down the thing it observes.

## Evaluation

The golden set (95 rows, 48 date-scoped) is the foundation of every reported
number, so its shape is a tested invariant rather than a convention:
`tests/test_golden_dataset.py` enforces minimum counts per difficulty and rejects
a temporal row that asserts nothing falsifiable.

Metric definitions are pure functions ([`evals/project_metrics.py`](../evals/project_metrics.py))
with their own unit tests, and CI compares measured values against committed
floors in `evals/thresholds.json`. The rules those metrics follow — chiefly that
"not measured" is `null` and never `0.0` — are in
[ADR 0007](adr/0007-metrics-that-can-fail.md).

## Swappability

Every model sits behind a stable interface ([ADR 0006](adr/0006-swappable-models-behind-interfaces.md)):
the LLM behind `complete()`, embeddings behind `embed_query()`, retrieval behind
`retrieve(strategy=...)`. This is what let the project run on a free Groq key and
a small embedding model under real hardware constraints while keeping the
spec's intended models a config change away.
