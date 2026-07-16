"""API routes.

Phase 0 exposes a single endpoint: /api/health. It doesn't just return 200 —
it checks whether the two backing services (Postgres, Qdrant) are reachable and
reports each. A health check that actually probes dependencies is what lets an
orchestrator (or you) know the system is *ready*, not merely *running*.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.security import rate_limit, require_api_key
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
    verified_citations: bool = True
    hallucinated_citations: list[str] = []
    cached: bool = False


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


@router.post(
    "/query",
    response_model=QueryResponse,
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
)
def query(req: QueryRequest) -> QueryResponse:
    """Answer a compliance question via the LangGraph agent.

    classify -> resolve_temporal -> retrieve -> generate -> verify -> respond,
    with out-of-scope questions routed to a refusal. Each call is logged (with the
    question PII-redacted) for observability.
    """
    import time

    from app.agent.graph import run_agent

    start = time.monotonic()
    result = run_agent(req.question, req.reference_date)
    latency_ms = int((time.monotonic() - start) * 1000)
    _log_query(req, result, latency_ms)
    return QueryResponse(**result)


def _log_query(req: QueryRequest, result: dict, latency_ms: int) -> None:
    """Best-effort query logging — never let logging break the response."""
    from app.db.queries import get_connection, insert_query_log
    from app.observability.redaction import redact

    try:
        with get_connection() as conn:
            insert_query_log(
                conn,
                {
                    "query_text": redact(req.question),
                    "reference_date": req.reference_date,
                    "in_force_docs": result.get("in_force_docs"),
                    "cited_doc_numbers": [c["doc_number"] for c in result.get("citations", [])],
                    "answer_text": result.get("answer"),
                    "degraded": result.get("degraded"),
                    "verified_citations": result.get("verified_citations"),
                    "latency_ms": latency_ms,
                },
            )
    except Exception:
        pass


@router.get("/documents")
def documents_list() -> list[dict]:
    """List all documents (for pickers and doc_number -> id lookup)."""
    from app.db.queries import get_connection, list_documents

    with get_connection() as conn:
        return list_documents(conn)


@router.get("/documents/{doc_id}")
def document_detail(doc_id: str) -> dict:
    """Document detail + its supersession history (predecessors & successors)."""
    from fastapi import HTTPException

    from app.db.queries import get_connection, get_document, supersession_history

    with get_connection() as conn:
        doc = get_document(conn, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="document not found")
        doc["supersession"] = supersession_history(conn, doc_id)
        return doc


@router.get("/documents/{doc_id}/supersession-graph")
def supersession_graph(doc_id: str) -> dict:
    """Graph nodes/edges around this document, for visualization."""
    from fastapi import HTTPException

    from app.db.queries import get_connection, get_document, supersession_history

    with get_connection() as conn:
        doc = get_document(conn, doc_id)
        if not doc:
            raise HTTPException(status_code=404, detail="document not found")
        history = supersession_history(conn, doc_id)

    nodes = {doc_id: {"id": doc_id, "doc_number": doc["doc_number"], "title": doc["title"]}}
    edges = []
    for p in history["predecessors"]:
        nodes[p["id"]] = {"id": p["id"], "doc_number": p["doc_number"], "title": p["title"]}
        edges.append({"from": p["id"], "to": doc_id, "relation": p["relation_type"]})
    for s in history["successors"]:
        nodes[s["id"]] = {"id": s["id"], "doc_number": s["doc_number"], "title": s["title"]}
        edges.append({"from": doc_id, "to": s["id"], "relation": s["relation_type"]})
    return {"nodes": list(nodes.values()), "edges": edges}
