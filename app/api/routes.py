"""API routes.

Phase 0 exposes a single endpoint: /api/health. It doesn't just return 200 —
it checks whether the two backing services (Postgres, Qdrant) are reachable and
reports each. A health check that actually probes dependencies is what lets an
orchestrator (or you) know the system is *ready*, not merely *running*.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import settings

router = APIRouter(prefix="/api")


# ---- /api/query request & response schemas (spec §12) ----
class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, description="Natural-language compliance question")
    reference_date: str | None = Field(None, description="ISO date; null = as of today")


class Citation(BaseModel):
    doc_number: str
    title: str
    url: str


class RetrievedSource(BaseModel):
    doc_number: str
    title: str
    section_heading: str | None = None
    score: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieved_sources: list[RetrievedSource]
    reference_date_used: str
    in_force_docs: int | None = None
    model: str | None
    degraded: bool


def _check_postgres() -> bool:
    """Return True if a trivial query against Postgres succeeds."""
    try:
        import psycopg

        with psycopg.connect(settings.database_url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
    except Exception:
        return False


def _check_qdrant() -> bool:
    """Return True if Qdrant answers its readiness probe."""
    try:
        from qdrant_client import QdrantClient

        client = QdrantClient(url=settings.qdrant_url, timeout=3)
        client.get_collections()  # cheap call that fails if Qdrant is down
        return True
    except Exception:
        return False


@router.get("/health")
def health() -> dict:
    """Liveness + readiness in one payload.

    The API itself always answers (that's liveness). The `services` block reports
    readiness of each dependency without ever crashing the endpoint.
    """
    services = {
        "postgres": "up" if _check_postgres() else "down",
        "qdrant": "up" if _check_qdrant() else "down",
    }
    return {
        "status": "ok",
        "service": "compliancegpt-api",
        "services": services,
    }


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    """Answer a compliance question with citations (Phase 1: dense retrieval)."""
    from app.agent.pipeline import answer_query

    result = answer_query(req.question, req.reference_date)
    return QueryResponse(**result)
