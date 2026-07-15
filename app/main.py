"""FastAPI application entrypoint.

Run locally with:  uvicorn app.main:app --reload
Then open http://localhost:8000/docs for the auto-generated API documentation
(FastAPI builds interactive OpenAPI docs for free — a real productivity win).
"""

from fastapi import FastAPI

from app.api.routes import router

app = FastAPI(
    title="ComplianceGPT API",
    description="Temporally-aware agentic RAG over RBI/SEBI regulatory documents.",
    version="0.0.1",
)

app.include_router(router)


@app.get("/")
def root() -> dict:
    """Friendly landing payload pointing at the docs."""
    return {"name": "ComplianceGPT", "docs": "/docs", "health": "/api/health"}
