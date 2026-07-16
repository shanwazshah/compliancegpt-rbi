# Deploying ComplianceGPT

The serving app loads local ML models (PyTorch), so plan for **~2 GB RAM**. This
does **not** fit truly-free tiers (Render free = 512 MB). Realistic hosts:

- A small **VPS** (Hetzner/DigitalOcean/Linode, ~$5–6/mo, 2 GB) — recommended.
- **Fly.io** with a 2 GB machine.
- Your own machine exposed via a tunnel (Cloudflare Tunnel / ngrok) — free, good
  enough for a demo link.

Truly free? Skip the live deploy and record a demo GIF of the local app for the
README (§20). The Docker artifacts below still prove it *is* deployable.

## One-command stack (any host with Docker)

```bash
# 1. Build + boot app, Postgres, Qdrant (migrations auto-run on first DB boot)
export LLM_API_KEY=gsk_your_groq_key
docker compose -f docker-compose.prod.yml up -d --build

# 2. Seed the corpus ONCE (scrape -> parse -> load -> embed -> graph).
#    Runs inside the app container; downloads the embedding model on first run.
docker compose -f docker-compose.prod.yml exec app python -m ingestion.scrapers.rbi_master_directions
docker compose -f docker-compose.prod.yml exec app python -m ingestion.load_documents
docker compose -f docker-compose.prod.yml exec app python -m ingestion.parsing.pdf_to_structured
docker compose -f docker-compose.prod.yml exec app python -m ingestion.indexing.embed_and_upsert
docker compose -f docker-compose.prod.yml exec app python -m ingestion.graph.supersession_builder

# 3. Verify
curl http://localhost:8000/api/health
```

Set `API_KEY=...` in the app environment to require `X-API-Key` on `/api/query`.

## Fly.io sketch

```bash
fly launch --no-deploy            # generates fly.toml; set VM to 2GB
fly secrets set LLM_API_KEY=gsk_...
fly deploy                        # builds the Dockerfile
```
Provision Postgres (`fly postgres create`) and run Qdrant as a second app or use
Qdrant Cloud's free tier; point `DATABASE_URL` / `QDRANT_URL` at them, then run
the seed steps via `fly ssh console`.

## Notes

- The image is CPU-only (installs `torch` from the CPU wheel index) to stay small.
- First `/api/query` after boot is slow (~15–30s) while the embedding model loads;
  subsequent queries are fast (and repeats are semantically cached).
- Data lives in the `postgres_data` and `qdrant_data` volumes — back these up
  rather than re-seeding.
