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


# ---- composition guards -------------------------------------------------
# The golden set is the foundation of every reported metric, so its shape is a
# tested invariant rather than a convention. These floors stop the set from
# quietly regressing to the near-empty temporal coverage it started with (1
# date-scoped row), which would make "temporal correctness" look measured while
# resting on a single example.

MIN_ROWS = 90
MIN_ADVERSARIAL_TEMPORAL = 25
MIN_OUT_OF_SCOPE = 8


def _count(rows, difficulty):
    return sum(1 for r in rows if r["difficulty"] == difficulty)


def test_golden_set_is_large_enough(rows):
    assert len(rows) >= MIN_ROWS, f"golden set shrank to {len(rows)} rows (floor {MIN_ROWS})"


def test_enough_adversarial_temporal_rows(rows):
    n = _count(rows, "adversarial_temporal")
    assert n >= MIN_ADVERSARIAL_TEMPORAL, (
        f"only {n} adversarial_temporal rows (floor {MIN_ADVERSARIAL_TEMPORAL}); "
        "temporal correctness is the project's headline metric and cannot rest on a "
        "handful of examples"
    )


def test_enough_out_of_scope_rows(rows):
    n = _count(rows, "out_of_scope")
    assert n >= MIN_OUT_OF_SCOPE, f"only {n} out_of_scope rows (floor {MIN_OUT_OF_SCOPE})"


def test_every_temporal_row_is_date_scoped_and_falsifiable(rows):
    """A date-scoped row must carry a date AND something it must not cite.

    Without `must_not_cite` the row asserts nothing an incorrect system would
    fail — it would be scored as passing for any answer that cites nothing.
    """
    for r in rows:
        if r["difficulty"] != "adversarial_temporal":
            continue
        assert r["reference_date"], f"temporal row without a date: {r['question']!r}"
        assert r.get("must_not_cite"), (
            f"temporal row asserts nothing: {r['question']!r}"
        )


def test_every_row_records_its_provenance(rows):
    """Generated rows must be distinguishable from hand-written ones."""
    for r in rows:
        assert r.get("source"), f"row missing `source`: {r['question']!r}"


def test_must_not_cite_never_overlaps_expected(rows):
    for r in rows:
        overlap = set(r.get("must_not_cite", [])) & set(r["expected_doc_numbers"])
        assert not overlap, f"row both expects and forbids {overlap}: {r['question']!r}"
