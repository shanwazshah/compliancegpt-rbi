"""Tests for the spec §14 project metrics.

These are the numbers that go in the README, so the scoring rules get the same
scrutiny as production code. The cases below encode the two ways a metric like
this is usually wrong in practice: rewarding a system for citing nothing, and
conflating "not measured" with "measured zero".
"""

from evals.project_metrics import (
    MetricResult,
    is_refusal,
    score_all,
    score_citation_accuracy,
    score_refusal_row,
    score_temporal_row,
)

MD = "RBI/DOR/2025-26/361"


def temporal_row(**over):
    row = {
        "question": "As of March 2023, what governed KYC for NBFCs?",
        "reference_date": "2023-03-21",
        "expected_doc_numbers": [],
        "must_not_cite": [MD],
        "difficulty": "adversarial_temporal",
    }
    row.update(over)
    return row


# ---- temporal correctness ----


def test_citing_a_not_yet_issued_direction_fails():
    assert score_temporal_row(temporal_row(), [MD]) is False


def test_citing_nothing_for_a_past_date_passes():
    # The in-force predecessor isn't in the vector index, so declining is right.
    assert score_temporal_row(temporal_row(), []) is True


def test_citing_any_other_current_direction_also_fails():
    # Stricter than just checking must_not_cite, and deliberately so: every
    # document in the index was issued on 2025-11-28, so *any* citation on a
    # 2023 question is a document that wasn't in force at the reference date.
    assert score_temporal_row(temporal_row(), ["RBI/DOR/2025-26/999"]) is False


def test_row_expecting_a_document_must_actually_cite_it():
    row = temporal_row(expected_doc_numbers=["RBI/DBR/2015-16/18"])
    assert score_temporal_row(row, []) is False
    assert score_temporal_row(row, ["RBI/DBR/2015-16/18"]) is True


def test_non_temporal_rows_are_not_scored():
    assert score_temporal_row({"difficulty": "easy", "must_not_cite": [MD]}, [MD]) is None


def test_row_that_asserts_nothing_is_not_scored():
    # Without must_not_cite the row cannot fail, so counting it would inflate
    # the metric with free passes.
    assert score_temporal_row(temporal_row(must_not_cite=[]), [MD]) is None


# ---- refusal correctness ----


def test_refusal_requires_both_no_citation_and_a_decline():
    row = {"difficulty": "out_of_scope"}
    assert score_refusal_row(row, [], "This is outside the scope of RBI regulation.") is True
    # Cited nothing but answered confidently anyway — still wrong.
    assert score_refusal_row(row, [], "The GST deadline is the 20th of each month.") is False
    # Declined but cited a regulation anyway.
    assert score_refusal_row(row, [MD], "This is outside the scope.") is False


def test_is_refusal_detects_common_phrasings():
    assert is_refusal("The provided context does not contain that information.")
    assert is_refusal("I do not have enough information to answer confidently.")
    assert not is_refusal("An NBFC must re-verify KYC every two years.")


# ---- citation accuracy ----


def test_real_but_unexpected_citation_counts_as_wrong():
    correct, total = score_citation_accuracy(
        cited=["RBI/DOR/2025-26/347"], expected=[MD], known_doc_numbers={MD, "RBI/DOR/2025-26/347"}
    )
    assert (correct, total) == (0, 1)


def test_hallucinated_citation_counts_as_wrong():
    correct, total = score_citation_accuracy(
        cited=["RBI/FAKE/9999-99/1"], expected=[MD], known_doc_numbers={MD}
    )
    assert (correct, total) == (0, 1)


def test_expected_citation_counts_as_correct():
    correct, total = score_citation_accuracy(cited=[MD], expected=[MD], known_doc_numbers={MD})
    assert (correct, total) == (1, 1)


def test_citing_nothing_contributes_no_denominator():
    # Otherwise a system that never cites anything would score 100%.
    assert score_citation_accuracy(cited=[], expected=[MD]) == (0, 0)


# ---- MetricResult: "not measured" is not zero ----


def test_metric_with_no_scorable_rows_is_none_not_zero():
    m = MetricResult("temporal_correctness")
    assert m.value is None
    assert "n/a" in m.render()


def test_metric_that_measured_total_failure_is_zero_not_none():
    m = MetricResult("temporal_correctness")
    m.add(False, "q")
    assert m.value == 0.0


def test_harness_excludes_degraded_answers():
    """A degraded answer is an outage, not an answer.

    Regression test for a real incident: the agent catches LLM failures and
    returns degraded=True instead of raising (spec §15 graceful degradation), so
    the harness scored those rows as real answers. With the LLM down nothing was
    cited, every "must not cite" row passed trivially, and the run reported
    temporal correctness 100% off a total outage.
    """
    import evals.run_evals as harness

    class FakeGraph:
        @staticmethod
        def run_agent(question, reference_date=None, use_cache=True):
            return {
                "answer": "The answer service is unavailable.",
                "citations": [],
                "degraded": True,
            }

    import sys
    import types

    fake = types.ModuleType("app.agent.graph")
    fake.run_agent = FakeGraph.run_agent
    original = sys.modules.get("app.agent.graph")
    sys.modules["app.agent.graph"] = fake
    try:
        results = harness.end_to_end([{**temporal_row(), "expected_doc_numbers": []}])
    finally:
        if original is not None:
            sys.modules["app.agent.graph"] = original
        else:
            del sys.modules["app.agent.graph"]

    assert all("error" in r for r in results), "degraded rows must be excluded, not scored"


def test_score_all_separates_the_three_metrics():
    results = [
        {"row": temporal_row(), "cited": [MD], "answer": ""},
        {"row": temporal_row(), "cited": [], "answer": ""},
        {
            "row": {"difficulty": "out_of_scope", "question": "cricket?"},
            "cited": [],
            "answer": "That is outside the scope of RBI regulation.",
        },
        {
            "row": {"difficulty": "easy", "question": "kyc?", "expected_doc_numbers": [MD]},
            "cited": [MD],
            "answer": "...",
        },
    ]
    scored = score_all(results, known_doc_numbers={MD})
    assert scored["temporal_correctness"].value == 0.5   # 1 of 2
    assert scored["refusal_correctness"].value == 1.0
    assert scored["citation_accuracy"].value == 1.0
