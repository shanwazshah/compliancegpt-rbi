"""API routes.

Phase 0 exposes a single endpoint: /api/health. It doesn't just return 200 —
it checks whether the two backing services (Postgres, Qdrant) are reachable and
reports each. A health check that actually probes dependencies is what lets an
orchestrator (or you) know the system is *ready*, not merely *running*.
"""

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/api")


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
