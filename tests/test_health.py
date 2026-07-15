"""Phase 0 smoke test for the /api/health endpoint.

FastAPI's TestClient runs the app in-process (no separate server needed) but the
health handler still opens real connections, so with Docker up this doubles as an
integration test against live Postgres + Qdrant.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200():
    """The endpoint must always answer 200 (liveness)."""
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    # The services block must report on both dependencies.
    assert set(body["services"]) == {"postgres", "qdrant"}
