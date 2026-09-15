import json

import pytest

from evals.advanced_retrieval import evaluate, load_dataset, score_case


def row(**overrides):
    value = {
        "id": "checked-location",
        "question": "Where is the requirement?",
        "reference_date": "2026-09-09",
        "expected_doc_number": "RBI/1",
        "expected_pages": [4],
        "review_status": "source_location_checked",
    }
    value.update(overrides)
    return value


def test_score_case_separates_document_and_physical_page_recall():
    hits = [
        {
            "doc_number": "RBI/1",
            "page_start": 2,
            "page_end": 2,
            "version_id": "version",
            "evidence_id": "version:2",
        },
        {
            "doc_number": "RBI/1",
            "page_start": 4,
            "page_end": 4,
            "version_id": "version",
            "evidence_id": "version:4",
        },
    ]
    result = score_case(row(), hits, lambda hit: hit["evidence_id"] == "version:4")
    assert result["document_rank"] == 1
    assert result["page_rank"] == 2
    assert result["resolved_evidence"] == 1
    assert result["returned_evidence"] == 2


def test_evaluate_records_errors_as_misses_without_erasing_other_rows():
    def retriever(question, **kwargs):
        if question == "broken":
            raise RuntimeError("navigator unavailable")
        return [
            {
                "doc_number": "RBI/1",
                "page_start": 4,
                "page_end": 4,
                "evidence_id": "version:4",
            }
        ]

    report = evaluate(
        [row(id="ok"), row(id="failed", question="broken")],
        "pageindex",
        8,
        retriever,
        lambda hit: True,
    )
    assert report["metrics"]["document_recall_at_k"]["value"] == 0.5
    assert report["metrics"]["physical_page_recall_at_k"]["value"] == 0.5
    assert report["metrics"]["retrieval_errors"] == 1
    assert report["results"][1]["error"] == "RuntimeError: navigator unavailable"


def test_load_dataset_rejects_unchecked_and_duplicate_rows(tmp_path):
    unchecked = tmp_path / "unchecked.jsonl"
    unchecked.write_text(json.dumps(row(review_status="draft")), encoding="utf-8")
    with pytest.raises(ValueError, match="not checked"):
        load_dataset(unchecked)

    duplicate = tmp_path / "duplicate.jsonl"
    line = json.dumps(row())
    duplicate.write_text(f"{line}\n{line}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(duplicate)
