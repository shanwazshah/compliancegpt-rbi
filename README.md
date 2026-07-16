# ComplianceGPT

**A temporally-aware agentic RAG system for RBI/SEBI regulatory compliance.**

Answers Indian banking/NBFC/fintech compliance questions over the RBI & SEBI
corpus with verifiable citations, and — crucially — knows which rules are
*currently in force* versus *historically superseded*. Built around the RBI's
28 Nov 2025 consolidation of ~9,445 circulars into 244 Master Directions.

> ⚠️ Decision-support tool, **not legal advice.** Every answer is traceable to a
> source document, but final compliance decisions rest with a qualified human.

## Status

🚧 In active development — **Phase 1 (MVP) complete.** Full pipeline works end
to end: scrape 30 RBI NBFC Master Directions → parse → chunk → embed → retrieve →
generate cited answers. See build plan in [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) §18.

**Phase 1 eval** (dense-only retrieval, 30-question golden set — full report in
[evals/reports/](evals/reports/phase1_manual_eval.md)):

| Metric | Result |
|---|---|
| Recall@5 | 92.3% |
| MRR | 0.811 |
| Citation accuracy (sample) | correct doc cited on all sampled answerable Qs |
| Refusal on out-of-scope | correctly declined |

The two retrieval misses were semantically-similar documents — motivating the
hybrid (dense + keyword) retrieval planned for Phase 2.

### Notable engineering decisions (MVP, all swappable)

- **LLM:** free open-source Llama 3.3 70B via Groq (OpenAI-compatible), no vendor
  lock-in — set `LLM_PROVIDER=anthropic` for Claude.
- **PDF parser:** pdfplumber (Docling is the `[docling]` extra; it needs more RAM).
- **Embeddings:** `bge-small-en-v1.5` (spec's `bge-m3` documented for higher-RAM/disk).

## Quickstart

```bash
docker compose up -d                                   # Postgres + Qdrant
python -m venv .venv && .venv\Scripts\activate         # (bash: source .venv/bin/activate)
pip install -e ".[dev]"
uvicorn app.main:app --reload                          # http://localhost:8000/docs
```

Health check: <http://localhost:8000/api/health>

Full architecture, schema, and design rationale live in
[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md).
