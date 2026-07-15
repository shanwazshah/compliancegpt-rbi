# CLAUDE.md

ComplianceGPT — a temporally-aware agentic RAG system that answers RBI/SEBI
regulatory-compliance questions with verifiable citations, distinguishing rules
currently in force from historically superseded ones.

> Full spec: [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md). This file stays short —
> put durable details in the spec, not here.

## Commands

```bash
# Boot databases (Postgres + Qdrant)
docker compose up -d
docker compose down            # stop;  add -v to also wipe data volumes

# Python env (Windows paths shown; use .venv/bin on macOS/Linux)
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# Run the API  ->  http://localhost:8000/docs
.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# Test + lint (what CI runs)
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check .

# Apply a new migration manually (initdb only auto-runs on first DB boot)
docker exec -i compliance_postgres psql -U compliance -d compliancegpt < migrations/000X_*.sql
```

## Directory map

```
app/          Serving plane — FastAPI + (later) LangGraph agent
  api/        HTTP routes
  agent/      LangGraph nodes (Phase 2)
  retrieval/  hybrid search + temporal filter (Phase 2)
  db/         Postgres models & queries
ingestion/    Batch plane — scrape -> parse -> graph -> chunk -> embed -> index
evals/        Golden set + eval harness (Phase 1 v0, Phase 2 full)
migrations/   Ordered *.sql; postgres auto-runs them on first boot
tests/        pytest
docs/         PROJECT_SPEC.md + ADRs
```

## Conventions

- **Config** goes through `app/config.py` (`from app.config import settings`);
  never read `os.environ` directly elsewhere.
- **Secrets** live in `.env` (git-ignored). `.env.example` is the template.
- **DB credentials** are duplicated in `docker-compose.yml` and `.env` — keep in sync.
- **Migrations** are append-only, numbered `NNNN_name.sql`. Don't edit an applied one.
- **Phase discipline:** build in phase order (see spec §18). Don't pull Phase 2
  features forward until Phase 1's Definition of Done is met.
