# ComplianceGPT

**A temporally-aware agentic RAG system for RBI/SEBI regulatory compliance.**

Answers Indian banking/NBFC/fintech compliance questions over the RBI & SEBI
corpus with verifiable citations, and — crucially — knows which rules are
*currently in force* versus *historically superseded*. Built around the RBI's
28 Nov 2025 consolidation of ~9,445 circulars into 244 Master Directions.

> ⚠️ Decision-support tool, **not legal advice.** Every answer is traceable to a
> source document, but final compliance decisions rest with a qualified human.

## Status

🚧 In active development — **Phase 0 (setup) complete.** See build plan in
[docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md) §18.

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
