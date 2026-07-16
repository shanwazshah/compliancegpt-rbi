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

**Retrieval ablation** (30-question golden set, K=5 — full report in
[evals/reports/](evals/reports/ablation_retrieval.md)). Real measured numbers,
reported honestly:

| Strategy | Recall@5 | MRR |
|---|---|---|
| **dense** | **92.3%** | **0.811** |
| bm25 | 92.3% | 0.655 |
| hybrid (dense+BM25, RRF) | 92.3% | 0.728 |
| hybrid + rerank | 88.5% | 0.735 |

**Honest finding:** on this clean corpus (each document is a distinct topic),
dense retrieval is already near-ceiling, and the advanced strategies did not beat
it in aggregate. The ablation is still valuable — it shows *why*: BM25 individually
rescued both of dense's misses (precise terms like "capital adequacy"), and the
cross-encoder reranker pulled one from unranked to **rank 1** — proving the
mechanism — but the small out-of-domain reranker misjudged two legal queries,
and the golden set lacks the regulation-identifier queries where lexical search
wins most. Generation quality (citations, refusals, disclaimer) is verified
separately in the Phase 1 report.

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
