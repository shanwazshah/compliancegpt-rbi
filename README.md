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
- **Temporal correctness (signature feature).** A supersession graph + a
  pre-retrieval temporal filter compute the set of documents *in force at a given
  date*. Ask "as of June 2024" and it refuses to cite the Nov-2025 Master Direction.
- **Agentic pipeline (LangGraph).** `classify → resolve_temporal → retrieve →
  generate → verify → respond`, with out-of-scope questions routed to a refusal.
- **Hybrid retrieval + reranking**, ablated honestly (see below).
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

Retrieval ablation on a 30-question golden set (K=5) —
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

Other verified behaviors: correct citations + disclaimer on answerable questions,
correct refusal on out-of-scope questions, temporal filter excludes not-yet-issued
docs for past dates, and 3/3 prompt-injection attempts resisted
([report](evals/reports/injection_test.md)).

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

Phases 0–2 complete; Phase 3 (production-readiness) in progress. Build plan:
[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) §18.
