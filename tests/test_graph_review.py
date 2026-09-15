from datetime import date

from ingestion.graph.review import render_review_packet


def test_review_packet_contains_full_provenance_and_source_context():
    relation = {
        "id": "relation-1",
        "predicate": "REQUIRES",
        "canonical_name": "RBI/1 :: Maintain a minimum ratio",
        "source_version_id": "version-1",
        "source_page": 4,
        "evidence_quote": "The minimum ratio is 15 percent.",
        "doc_number": "RBI/1",
        "title": "Synthetic Direction",
        "source_url": "https://example.org/source",
        "valid_from": date(2026, 1, 1),
        "valid_to": None,
        "text": "Full page. The minimum ratio is 15 percent. An exception follows.",
    }
    packet = render_review_packet([relation], "candidate")
    assert "Knowledge-graph review packet: candidate" in packet
    assert "`relation-1`" in packet
    assert "Physical page: 4" in packet
    assert "https://example.org/source" in packet
    assert "An exception follows." in packet