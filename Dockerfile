# Production image for the ComplianceGPT serving app (FastAPI + agent).
# CPU-only; the ML models (bge-small, MiniLM reranker) load at runtime.
FROM python:3.12-slim

# System deps: build tools for any wheels that need them; curl for healthcheck.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install a CPU-only torch first (much smaller than the default CUDA build),
# then the project. Layer caching keeps rebuilds fast.
COPY pyproject.toml ./
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -e .

# App code (data/ and .venv are excluded via .dockerignore).
COPY . .

EXPOSE 8000

# HTTP healthcheck against the readiness endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
