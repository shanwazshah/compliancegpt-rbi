"""Regression tests for the foundation required by vectorless retrieval."""

import types
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.agent.cache import ExactCache
from app.agent.nodes.classify import classify_query
from app.agent.nodes.expand import expand_context
from app.agent.nodes.groundedness import compute_groundedness
from app.api import routes, security
from app.config import settings


def test_cache_is_exact_scoped_and_returns_defensive_copies():
    cache = ExactCache()
    key = ("KYC?", "2026-09-05", "revision1", "pageindex")
    cache.put(key, {"answer": "original", "citations": []})
    result = cache.get(key)
    result["citations"].append("changed")
    assert cache.get(key)["citations"] == []
    assert cache.get(("KYC?", "2026-09-06", "revision1", "pageindex")) is None
    assert cache.get(("KYC?", "2026-09-05", "revision2", "pageindex")) is None
    assert cache.get(("KYC?!", "2026-09-05", "revision1", "pageindex")) is None


def test_cache_expires_and_evicts():
    cache = ExactCache(max_size=1, ttl_seconds=2)
    with patch("app.agent.cache.time.monotonic", return_value=0):
        cache.put(("a",), {"answer": "A"})
        cache.put(("b",), {"answer": "B"})
        assert cache.get(("a",)) is None
    with patch("app.agent.cache.time.monotonic", return_value=3):
        assert cache.get(("b",)) is None


def test_rotating_unvalidated_api_header_does_not_bypass_limit(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "rate_limit_per_min", 1)
    security._hits.clear()
    request = types.SimpleNamespace(client=types.SimpleNamespace(host="audit-test"))
    security.rate_limit(request, "invented-one")
    with pytest.raises(HTTPException) as error:
        security.rate_limit(request, "invented-two")
    assert error.value.status_code == 429
    security._hits.clear()


def test_long_parent_preserves_distant_retrieved_children():
    parent = "a" * 4000 + "FIRST_MATCH" + "b" * 5000 + "SECOND_MATCH"
    hits = [
        {"doc_number": "DOC", "parent_index": 1, "parent_text": parent, "text": text}
        for text in ("FIRST_MATCH", "SECOND_MATCH")
    ]
    expanded = expand_context(hits)
    assert any("FIRST_MATCH" in hit["text"] for hit in expanded)
    assert any("SECOND_MATCH" in hit["text"] for hit in expanded)


def test_full_child_is_preserved_at_window_boundary():
    child = "x" * 2100
    hit = {"doc_number": "DOC", "text": child, "parent_text": "a" * 4000 + child + "b" * 4000}
    assert child in expand_context([hit])[0]["text"]


def test_wrong_numeric_fact_cannot_have_perfect_groundedness():
    contexts = [{"text": "The minimum ratio is 15 percent."}]
    assert compute_groundedness("The minimum ratio is 99 percent.", contexts) == 0


def test_citation_identifiers_do_not_count_as_numeric_claims():
    contexts = [{"text": "The minimum ratio is 15 percent."}]
    assert compute_groundedness("The minimum ratio is 15 percent. [E:12345678:2]", contexts) > 0.8


@pytest.mark.parametrize("value", ["not-a-date", "2026-02-30", "2026-13-01"])
def test_invalid_request_dates_fail_validation(value):
    with pytest.raises(ValidationError):
        routes.QueryRequest(question="KYC rules?", reference_date=value)


@pytest.mark.parametrize(
    "output", ['{"in_scope":"false"}', '{"in_scope":true,"reference_date":"bad"}', "{}"]
)
def test_malformed_classification_never_falls_back_to_today(output):
    with patch("app.agent.nodes.classify.complete", return_value=output):
        with pytest.raises(ValueError, match="safely"):
            classify_query("What applied in 2024?")


def test_vectorless_readiness_does_not_contact_qdrant(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_strategy", "pageindex")
    with (
        patch.object(routes, "_check_postgres", return_value=False),
        patch.object(routes, "_check_qdrant", side_effect=AssertionError("vector DB called")),
    ):
        response = routes.readiness()
    assert response.status_code == 503
