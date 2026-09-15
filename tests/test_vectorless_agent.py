"""Full agent routing with a fake evidence repository and deterministic LLM outputs."""

from contextlib import nullcontext

from fastapi.testclient import TestClient

from app.agent import graph
from app.agent.cache import ExactCache
from app.api import routes
from app.config import settings
from app.main import app
from app.retrieval import pageindex_search

VERSION = "12345678-1234-5678-1234-567812345678"


class Repository:
    def candidates(self, query, allowed, ref, limit):
        assert allowed == {"RBI/DOR/2025-26/361"}
        return [
            {
                "version_id": VERSION,
                "doc_number": "RBI/DOR/2025-26/361",
                "title": "Synthetic KYC fixture",
                "source_url": "https://example.org/kyc",
                "index_kind": "pageindex",
            }
        ]

    def nodes(self, version_id):
        return [
            {
                "node_id": "n1",
                "parent_id": None,
                "title": "Requirements",
                "summary": "A synthetic test requirement",
                "page_start": 1,
                "page_end": 1,
            }
        ]

    def pages(self, version_id, numbers):
        assert version_id == VERSION and numbers == [1]
        return [{"page_number": 1, "text": "The minimum ratio is 15 percent."}]

    def graph_neighbors(self, *args):
        return []


def setup_pipeline(monkeypatch):
    monkeypatch.setattr(graph, "_agent", None)
    monkeypatch.setattr(graph, "_cache", ExactCache())
    monkeypatch.setattr(graph, "get_connection", lambda: nullcontext(object()))
    monkeypatch.setattr(graph, "in_force_doc_numbers", lambda *args: {"RBI/DOR/2025-26/361"})
    monkeypatch.setattr(graph, "corpus_revision", lambda *args: "revision-1")
    monkeypatch.setattr(
        graph, "classify_query", lambda q: {"in_scope": True, "reference_date": "2026-09-05"}
    )
    monkeypatch.setattr(pageindex_search, "get_connection", lambda: nullcontext(object()))
    monkeypatch.setattr(pageindex_search, "EvidenceRepository", lambda conn: Repository())
    monkeypatch.setattr(settings, "pageindex_navigation_mode", "llm")
    monkeypatch.setattr(pageindex_search, "complete", lambda *args, **kwargs: '{"node_ids":["n1"]}')
    monkeypatch.setattr(
        graph,
        "generate_answer",
        lambda *args: {
            "answer": f"The minimum ratio is 15 percent. [E:{VERSION}:1]",
            "model": "fixture-model",
        },
    )


def test_pageindex_api_returns_exact_page_citations(monkeypatch):
    setup_pipeline(monkeypatch)
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "rate_limit_per_min", 0)
    monkeypatch.setattr(routes, "_log_query", lambda *args: None)
    response = TestClient(app).post(
        "/api/query",
        json={
            "question": "What ratio applies?",
            "strategy": "pageindex",
            "reference_date": "2026-09-05",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verified_citations"]
    assert body["retrieval_strategy"] == "pageindex"
    assert body["citations"][0]["evidence_id"] == f"{VERSION}:1"
    assert body["citations"][0]["page_start"] == 1
    assert body["retrieved_sources"][0]["text"] == "The minimum ratio is 15 percent."


def test_agent_cache_respects_resolved_date_and_corpus_revision(monkeypatch):
    setup_pipeline(monkeypatch)
    first = graph.run_agent("KYC?", strategy="pageindex")
    second = graph.run_agent("KYC?", strategy="pageindex")
    assert not first["cached"] and second["cached"]
    monkeypatch.setattr(graph, "corpus_revision", lambda *args: "revision-2")
    assert not graph.run_agent("KYC?", strategy="pageindex")["cached"]
    monkeypatch.setattr(
        graph, "classify_query", lambda q: {"in_scope": True, "reference_date": "2026-09-06"}
    )
    assert not graph.run_agent("KYC?", strategy="pageindex")["cached"]


def test_unknown_page_citation_is_withheld(monkeypatch):
    setup_pipeline(monkeypatch)
    monkeypatch.setattr(
        graph,
        "generate_answer",
        lambda *args: {"answer": "A fabricated fact. [E:unknown:7]", "model": "fixture-model"},
    )
    response = graph.run_agent("KYC?", strategy="pageindex", use_cache=False)
    assert not response["verified_citations"]
    assert "A fabricated fact" not in response["answer"]
    assert response["citations"] == []


def test_empty_temporal_scope_never_calls_navigation_or_generation(monkeypatch):
    setup_pipeline(monkeypatch)
    monkeypatch.setattr(graph, "in_force_doc_numbers", lambda *args: set())

    def forbidden(*args, **kwargs):
        raise AssertionError("No LLM calls should follow an empty temporal scope")

    monkeypatch.setattr(graph, "generate_answer", forbidden)
    monkeypatch.setattr(pageindex_search, "complete", forbidden)
    response = graph.run_agent("KYC?", strategy="pageindex", use_cache=False)
    assert "No applicable source text" in response["answer"]
    assert response["citations"] == []
