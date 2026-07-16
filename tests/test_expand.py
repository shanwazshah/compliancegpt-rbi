"""Unit tests for parent-chunk expansion (small-to-big)."""

from app.agent.nodes.expand import expand_context


def test_children_sharing_a_parent_collapse_to_one_block():
    hits = [
        {"doc_number": "A", "parent_index": 1, "text": "child1", "parent_text": "SECTION-1"},
        {"doc_number": "A", "parent_index": 1, "text": "child2", "parent_text": "SECTION-1"},
        {"doc_number": "A", "parent_index": 2, "text": "child3", "parent_text": "SECTION-2"},
    ]
    out = expand_context(hits)
    assert len(out) == 2  # deduped by (doc, parent)
    assert out[0]["text"] == "SECTION-1"  # uses fuller parent text
    assert out[1]["text"] == "SECTION-2"


def test_falls_back_to_child_text_when_no_parent():
    hits = [{"doc_number": "B", "parent_index": None, "text": "only-child"}]
    out = expand_context(hits)
    assert out[0]["text"] == "only-child"
