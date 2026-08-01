# ComplianceGPT

**A temporally-aware agentic RAG system for RBI/SEBI regulatory compliance.**

Answers Indian banking / NBFC / fintech compliance questions over the RBI (and,
later, SEBI) corpus with **verifiable citations**, and — its defining property —
knows which rules are *currently in force* versus *historically superseded*.

> ⚠️ **Decision-support tool, not legal advice.** Every answer is traceable to a
> source document, but final compliance decisions rest with a qualified human.

## Why now

On **28 November 2025** the RBI consolidated ~**9,445 circulars** into **244
Master Directions**, formally withdrawing thousands of source circulars. That
makes "what does the rule say *now*" vs "what did it say *as of [past date]*" a
concrete, high-stakes problem — and exactly what this system is built to answer.
Naive similarity RAG can't: it will happily cite a superseded circular that is
semantically perfect but no longer in force.

## What it does

- **Cited answers.** Every factual claim cites a real document number; a
  post-generation **verify step flags hallucinated citations**.
- **Temporal correctness (signature feature).** A supersession graph built from
  RBI's own published withdrawal list — **574 withdrawn NBFC circulars, 426 with
  issue dates verified from each circular's own page** — plus a pre-retrieval
  temporal filter that computes the set of documents *in force at a given date*.
  Ask "as of June 2024" and the Nov-2025 Master Direction is excluded before
  similarity search ever runs.
- **Agentic pipeline (LangGraph).** `classify → resolve_temporal → retrieve →
  expand → generate → verify → groundedness → respond`, with out-of-scope
  questions routed to a refusal.
- **Hybrid retrieval + reranking**, ablated honestly (see below).
- **Measured, not asserted.** Per-node latency and per-query token cost are
  recorded on every request; the golden set carries **95 rows, 48 of them
  date-scoped**; and a CI gate fails the build when a metric regresses past a
  committed floor.
- **Production touches.** API-key auth, rate limiting, PII-redacted query logging.

## Architecture

```
  INGESTION (batch)                          SERVING (online)
  scrape RBI MDs                             FastAPI  ── LangGraph agent:
    → parse (pdfplumber)                       classify → resolve_temporal
    → documents (Postgres)                     → retrieve (dense/BM25/hybrid)
    → chunk → embed (BGE-small)                → generate (Groq Llama)
    → Qdrant (vectors + payload)               → verify_citations → respond
    → supersession graph (Postgres)                    │
                                               Postgres: documents,
  Postgres ── Qdrant ─────────────────────────  supersession_edges, query_logs
```

## Eval results (real, measured, reported honestly)

### The corpus and the graph

| | Count |
|---|---|
| NBFC Master Directions indexed (Nov 2025 consolidation) | **30** |
| Chunks embedded in Qdrant | **868** |
| Withdrawn circulars ingested from RBI's published index | **574** |
| …of those, issue date verified from the circular's own page | **426** |
| Documents in Postgres (30 active + 465 superseded) | **495** |
| Supersession edges (102 title-matched + 1 hand-verified) | **103** |

### The temporal filter, measured against the real graph

The number of documents in force, by reference date — the Nov-2025 consolidation
visible as a single-day event:

| Reference date | In force | of which Nov-2025 MDs |
|---|---|---|
| 2018-06-30 | 430 | **0** |
| 2024-06-30 | 460 | **0** |
| 2025-11-27 | 465 | **0** |
| **2025-11-28** | **30** | **30** |
| 2026-08-01 | 30 | 30 |

End-to-end, the same question at two dates:

```
"What is the periodic KYC updation cycle for a low-risk NBFC customer?"

  as of today       →  30 docs in force  →  cites RBI/DOR/2025-26/361, 10-year cycle
  as of 2024-06-30  → 460 docs in force  →  cites nothing: "the reference context
                                            does not contain any information"
```

The 2025 Master Direction is excluded *before* similarity search runs, so it
cannot be retrieved for a 2024 question however well it matches the text.

### Retrieval

Measured on the 95-row golden set (37 answerable rows, K=5):

| Metric | Value |
|---|---|
| **Recall@5** | **94.6%** |
| **MRR** | **0.794** |

Strategy ablation on the earlier 30-question set —
[full report](evals/reports/ablation_retrieval.md):

| Strategy | Recall@5 | MRR |
|---|---|---|
| **dense** (default) | **92.3%** | **0.811** |
| bm25 | 92.3% | 0.655 |
| hybrid (RRF) | 92.3% | 0.728 |
| hybrid + rerank | 88.5% | 0.735 |

On this clean corpus dense is already near-ceiling; the advanced strategies did
not beat it in aggregate, and we default to the measured-best rather than the
fanciest (spec's honesty requirement). See
[ADR 0002](docs/adr/0002-why-hybrid-retrieval.md) for the analysis.

### Generation metrics — blocked on LLM quota, not on capability

The harness is built and unit-tested. The blocker is arithmetic, not engineering:
the full 95-row eval costs **~432,000 tokens** (~4,500 per row across classify →
generate → groundedness, since generation sends expanded parent context), against
a **100,000 tokens/day** free-tier allowance. The last run scored 22 of 95 rows
before the daily limit hit, and the harness **refused to report** metrics computed
on that 23% sample:

```
!! Only 22/95 rows produced a scorable answer (23%). Reporting the project
   metrics as NOT MEASURED rather than computing them over the survivors.
```

| Metric | Status |
|---|---|
| Citation accuracy | scored by [`project_metrics.py`](evals/project_metrics.py); needs ~432k tokens |
| Temporal correctness | same |
| Refusal correctness | same |
| Injection resistance / hallucination rate | [35-case red-team suite](evals/red_team.py) built; run pending |
| Faithfulness / answer relevancy | last run failed 6/6 on rate limits, reported as `n/a` not `0.0` ([report](evals/reports/generation_metrics.md)) |

Unblocking it is a config change, not a code change ([ADR 0006](docs/adr/0006-swappable-models-behind-interfaces.md)):
a paid tier, a local Ollama endpoint, or routing the two cheap nodes (classify,
groundedness) to a smaller model so the 70B quota is spent only on generation.

**Why this section is worth reading.** The first full run of this harness
reported *temporal correctness 100%* — and it was false. An expired API key sent
every generation down the agent's graceful-degradation path, which returns a
well-formed response containing no answer instead of raising. Nothing was cited
anywhere, and since a date-scoped row passes by not citing anything wrong, all 48
temporal rows passed trivially. The giveaway was the combination: a system truly
scoring 100% on temporal correctness cannot also produce zero citations.

The harness now excludes degraded answers, refuses to report at all when fewer
than half the rows survive, and has a regression test pinning both.
[ADR 0007](docs/adr/0007-metrics-that-can-fail.md) records the incident and the
four rules that follow from it — chiefly that "not measured" is `null` and never
`0.0`, while a measured `0.0` still fails the CI gate.

## Quickstart (< 5 commands)

```bash
docker compose up -d                                   # Postgres + Qdrant
python -m venv .venv && .venv\Scripts\activate         # (bash: source .venv/bin/activate)
pip install -e ".[dev]"
cp .env.example .env      # then set LLM_API_KEY (free Groq key: console.groq.com)
uvicorn app.main:app --reload                          # http://localhost:8000/docs
```

Ingest the corpus (one-time): `python -m ingestion.scrapers.rbi_master_directions`
then `... load_documents`, `... parsing.pdf_to_structured`,
`... indexing.embed_and_upsert`, `... graph.supersession_builder`. UI:
`streamlit run ui/streamlit_app.py`.

## Notable engineering decisions

Full rationale in [docs/adr/](docs/adr/). This project was built under real
hardware constraints, and every model/tool is **swappable behind a stable
interface** (see [ADR 0006](docs/adr/0006-swappable-models-behind-interfaces.md)):

| Layer | MVP default (fits constrained hardware) | Spec's intended |
|---|---|---|
| LLM | Groq `llama-3.3-70b` (free, open-source) | Claude / GPT-class |
| Embeddings | `bge-small-en-v1.5` | `bge-m3` |
| Reranker | `ms-marco-MiniLM-L-6-v2` | `bge-reranker-v2-m3` |
| PDF parser | pdfplumber | Docling |

## Status

Phase 0–1 complete. Phase 2 complete except RAGAS integration. Phase 3 in
progress: eval-gated CI, cost/latency instrumentation, API-key auth, rate
limiting, PII redaction, and prompt-injection hardening are in; a live public
demo is not. Build plan: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) §18.

Known gaps, kept here rather than discovered by a reader:

- **Langfuse export is optional and unverified against a live instance.** Per-node
  latency is recorded in-process regardless, so the numbers don't depend on it.
- **Withdrawn circulars are metadata-only.** Their PDFs aren't chunked or
  embedded, so a past-date query correctly declines rather than quoting the
  historical text. This bounds how temporal correctness is scored — see
  [ADR 0007](docs/adr/0007-metrics-that-can-fail.md).
- **CI enforces the eval *contract* on every PR** (golden-set composition, scorer
  behavior, gate logic) and the *measured* thresholds when a metrics file is
  present; a clean runner has no corpus and must not scrape RBI to build one.
- **SEBI is not ingested.** RBI NBFC Master Directions only.
