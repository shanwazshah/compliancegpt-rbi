"""Structural validation of the golden dataset.

The golden set is the foundation every metric sits on, so a malformed row would
silently corrupt the evals. These checks are pure-data (no corpus, no LLM), so
they run as a gate in CI where the full retrieval eval can't.
"""

import json
from pathlib import Path

import pytest

GOLDEN = Path("evals") / "golden_dataset.jsonl"
VALID_DIFFICULTY = {"easy", "medium", "hard", "adversarial_temporal", "out_of_scope"}
REQUIRED = {
    "question",
    "reference_date",
    "expected_doc_numbers",
    "expected_answer_summary",
    "difficulty",
    "category",
}


@pytest.fixture(scope="module")
def rows():
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(x) for x in lines if x.strip()]


def test_every_line_is_valid_json_with_required_fields(rows):
    assert rows, "golden dataset is empty"
    for r in rows:
        missing = REQUIRED - set(r)
        assert not missing, f"row missing {missing}: {r.get('question')!r}"


def test_difficulty_values_are_known(rows):
    for r in rows:
        assert r["difficulty"] in VALID_DIFFICULTY, f"bad difficulty: {r['difficulty']}"


def test_questions_are_unique(rows):
    questions = [r["question"] for r in rows]
    dupes = {q for q in questions if questions.count(q) > 1}
    assert not dupes, f"duplicate questions: {dupes}"


def test_out_of_scope_rows_expect_no_documents(rows):
    for r in rows:
        if r["difficulty"] == "out_of_scope":
            assert not r["expected_doc_numbers"], (
                f"out_of_scope row should expect no docs: {r['question']!r}"
            )


def test_expected_doc_numbers_look_like_real_doc_numbers(rows):
    for r in rows:
        for dn in r["expected_doc_numbers"]:
            assert dn.startswith(("RBI/", "SEBI/")), f"suspicious doc_number: {dn}"


def test_reference_dates_are_iso_or_null(rows):
    from datetime import date

    for r in rows:
        ref = r["reference_date"]
        if ref is not None:
            date.fromisoformat(ref)  # raises if malformed
