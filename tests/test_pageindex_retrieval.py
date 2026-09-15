"""Boundary and provenance tests; no external model or vector store needed."""

from datetime import date
from unittest.mock import patch

import pytest

from app.config import settings
from app.retrieval.pageindex_search import navigate, navigate_local, search, select_nodes
from ingestion.pageindex.adapter import normalize_tree


class Repository:
    def __init__(self):
        self.scopes = []
        self.reads = []

    def candidates(self, query, allowed, ref, limit):
        self.scopes.append((allowed, ref))
        return [
            {
                "version_id": "version-a",
                "doc_number": "A",
                "title": "KYC",
                "source_url": "https://example.org/a",
                "index_kind": "pageindex",
            }
        ]

    def nodes(self, version_id):
        return [
            {
                "node_id": "root",
                "parent_id": None,
                "title": "KYC",
                "summary": "Requirements",
                "page_start": 1,
                "page_end": 1,
            }
        ]

    def pages(self, version_id, numbers):
        self.reads.append((version_id, numbers))
        return [{"page_number": n, "text": "The minimum ratio is 15 percent."} for n in numbers]

    def graph_neighbors(self, frontier, allowed, ref):
        self.scopes.append((allowed, ref))
        return []

    def graph_evidence(self, query, doc_numbers, allowed, ref, limit):
        self.scopes.append((allowed, ref))
        return getattr(self, "concepts", [])


@pytest.fixture(autouse=True)
def use_llm_navigation(monkeypatch):
    monkeypatch.setattr(settings, "pageindex_navigation_mode", "llm")


def test_unknown_node_id_is_rejected():
    with patch("app.retrieval.pageindex_search.complete", return_value='{"node_ids":["outside"]}'):
        with pytest.raises(ValueError, match="outside"):
            select_nodes("question", [{"node_id": "allowed"}])


def test_retrieval_reads_selected_page_and_preserves_scope():
    repo = Repository()
    with patch("app.retrieval.pageindex_search.complete", return_value='{"node_ids":["root"]}'):
        result = search("KYC", 5, "graph_pageindex", {"A"}, "2024-01-01", repo)
    assert all(scope == ({"A"}, date(2024, 1, 1)) for scope in repo.scopes)
    assert repo.reads == [("version-a", [1])]
    assert result[0]["evidence_id"] == "version-a:1"
    assert result[0]["text"] == "The minimum ratio is 15 percent."


def test_verified_graph_concept_prioritizes_its_source_page(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_max_pages", 2)
    repo = Repository()
    repo.concepts = [
        {
            "id": "relation-1",
            "source": "A",
            "target": "A :: Update obligation",
            "target_kind": "obligation",
            "predicate": "REQUIRES",
            "evidence_quote": "The minimum ratio is 15 percent.",
            "source_version_id": "version-a",
            "source_page": 2,
            "score": 1.0,
        }
    ]
    repo.nodes = lambda version: [
        {"node_id": "root", "parent_id": None, "page_start": 1, "page_end": 1}
    ]
    with patch("app.retrieval.pageindex_search.select_nodes", return_value=["root"]):
        result = search("update obligation", 2, "graph_pageindex", {"A"}, "2024-01-01", repo)
    assert [hit["page_start"] for hit in result] == [2, 1]
    assert result[0]["graph_paths"][0]["predicate"] == "REQUIRES"


def test_missing_tree_is_a_visible_error_not_vector_fallback():
    repo = Repository()
    original = repo.candidates
    repo.candidates = lambda *args: [{**original(*args)[0], "index_kind": "pages"}]
    with pytest.raises(ValueError, match="no PageIndex tree"):
        search("KYC", 5, "pageindex", {"A"}, "2024-01-01", repo)


def test_navigation_has_a_hard_page_budget(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_max_pages", 2)
    nodes = [{"node_id": "root", "parent_id": None, "page_start": 1, "page_end": 100}]
    with patch("app.retrieval.pageindex_search.complete", return_value='{"node_ids":["root"]}'):
        assert navigate("question", nodes) == [1, 2]


def test_normalization_keeps_section_boundary_pages():
    tree = [
        {"node_id": "a", "title": "A", "page_index": 1},
        {"node_id": "b", "title": "B", "page_index": 3},
    ]
    normalized = normalize_tree(tree, 5)
    assert normalized[0]["page_end"] == 3
    assert normalized[1]["page_end"] == 5


@pytest.mark.parametrize(
    "tree",
    [
        [{"node_id": "a", "page_index": 0}],
        [{"node_id": "a", "page_index": 9}],
        [{"node_id": "a", "page_index": 1}, {"node_id": "a", "page_index": 2}],
    ],
)
def test_invalid_tree_provenance_is_rejected(tree):
    with pytest.raises(ValueError):
        normalize_tree(tree, 5)


def test_parent_opening_page_does_not_crowd_out_selected_evidence():
    nodes = [
        {"node_id": "root", "parent_id": None, "page_start": 1, "page_end": 90},
        {"node_id": "rule", "parent_id": "root", "page_start": 40, "page_end": 40},
    ]
    with patch(
        "app.retrieval.pageindex_search.complete",
        side_effect=['{"node_ids":["root"]}', '{"node_ids":["rule"]}'],
    ):
        assert navigate("question", nodes) == [40]


def test_empty_candidates_do_not_strand_continuation_page_budget(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_max_pages", 3)
    repo = Repository()
    original = repo.candidates
    repo.candidates = lambda *args: [{**original(*args)[0], "version_id": str(i)} for i in range(5)]
    repo.nodes = lambda version: [
        {"node_id": version, "parent_id": None, "page_start": 40, "page_end": 42}
    ]
    with patch("app.retrieval.pageindex_search.select_nodes", side_effect=[["0"], [], [], [], []]):
        hits = search("periodic updates", 3, "pageindex", {"A"}, "2024-01-01", repo)
    assert [h["page_start"] for h in hits] == [40, 41, 42]


def test_active_documents_share_total_page_budget(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_max_pages", 3)
    monkeypatch.setattr(settings, "retrieval_navigation_documents", 2)
    repo = Repository()
    original = repo.candidates
    repo.candidates = lambda *args: [{**original(*args)[0], "version_id": str(i)} for i in range(2)]
    repo.nodes = lambda version: [
        {"node_id": version, "parent_id": None, "page_start": 1, "page_end": 3}
    ]
    with patch("app.retrieval.pageindex_search.select_nodes", side_effect=[["0"], ["1"]]):
        hits = search("question", 3, "pageindex", {"A"}, "2024-01-01", repo)
    assert [(h["version_id"], h["page_start"]) for h in hits] == [("0", 1), ("1", 1), ("0", 2)]


def test_generation_normalizes_wrappers_without_hiding_unknown_ids():
    from app.agent.graph import _verify
    from app.agent.nodes.generate import generate_answer

    hit = {
        "doc_number": "RBI/DOR/2025-26/361",
        "title": "KYC",
        "source_url": "url",
        "citation_id": "E:version:41",
        "evidence_id": "version:41",
        "text": "Two years",
    }
    raw = "Two years \u3010Source 2 | RBI/DOR/2025-26/361 | citation: E:version:41\u3011"
    with patch("app.agent.nodes.generate.complete", return_value=raw):
        answer = generate_answer("question", [hit])["answer"]
    assert "[E:version:41]" in answer
    assert _verify({"answer": answer, "hits": [hit]})["verified"]
    assert not _verify({"answer": answer.replace("version:41", "unknown:99"), "hits": [hit]})[
        "verified"
    ]
    assert not _verify({"answer": "Two years", "hits": [hit]})["verified"]


@pytest.mark.parametrize("citation", ["[ E:version:41 ]", "\u3010 E:version:41 \u3011"])
def test_generation_normalizes_citation_whitespace(citation):
    from app.agent.nodes.generate import generate_answer

    with patch("app.agent.nodes.generate.complete", return_value="Two years " + citation):
        answer = generate_answer("question", [{"doc_number": "A", "text": "Two years"}])["answer"]
    assert "[E:version:41]" in answer


@pytest.mark.parametrize("identity,valid", [("version:41", True), ("unknown:99", False)])
def test_citation_label_wrapper_preserves_exact_identity(identity, valid):
    from app.agent.graph import _verify
    from app.agent.nodes.generate import generate_answer

    hit = {
        "doc_number": "A",
        "title": "KYC",
        "source_url": "url",
        "text": "Two years",
        "citation_id": "E:version:41",
        "evidence_id": "version:41",
    }
    with patch(
        "app.agent.nodes.generate.complete", return_value=f"Two years [citation: E:{identity}]"
    ):
        answer = generate_answer("question", [hit])["answer"]
    assert f"[E:{identity}]" in answer
    assert _verify({"answer": answer, "hits": [hit]})["verified"] is valid

def test_pageindex_bounds_the_number_of_navigated_documents(monkeypatch):
    monkeypatch.setattr(settings, "retrieval_navigation_documents", 1)
    repo = Repository()
    original = repo.candidates
    repo.candidates = lambda *args: [
        {**original(*args)[0], "version_id": str(i)} for i in range(3)
    ]
    with patch("app.retrieval.pageindex_search.select_nodes", return_value=["root"]) as select:
        hits = search("question", 3, "pageindex", {"A"}, "2024-01-01", repo)
    assert select.call_count == 1
    assert {hit["version_id"] for hit in hits} == {"0"}

def test_local_navigation_uses_tree_to_include_anchor_context_and_matching_section():
    nodes = [
        {
            "node_id": "ongoing",
            "parent_id": None,
            "title": "On-going Due Diligence",
            "summary": "Periodic KYC updates by customer risk category",
            "page_start": 40,
            "page_end": 45,
        },
        {
            "node_id": "reporting",
            "parent_id": None,
            "title": "Reporting",
            "summary": "Transaction reports",
            "page_start": 50,
            "page_end": 52,
        },
    ]
    pages = navigate_local(
        "periodic KYC update intervals",
        nodes,
        [{"page_number": 41, "rank": 1.0}],
    )
    assert pages[:3] == [41, 40, 42]
