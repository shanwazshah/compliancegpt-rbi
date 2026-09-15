"""Unit tests for the groundedness scorer (spec §11.8)."""

from app.agent.nodes.groundedness import compute_groundedness

CONTEXT = [
    {
        "text": (
            "The NBFC shall carry out periodic updation at least once in every "
            "two years for high-risk customers, once in every eight years for "
            "medium risk customers and once in every 10 years for low-risk customers."
        )
    }
]


def test_grounded_answer_scores_high():
    answer = "Periodic updation for low-risk customers is once in every 10 years."
    assert compute_groundedness(answer, CONTEXT) > 0.8


def test_hallucinated_answer_scores_low():
    # Terms that appear nowhere in the context.
    answer = "Cryptocurrency mining licences require quarterly biometric drone audits."
    assert compute_groundedness(answer, CONTEXT) < 0.4


def test_empty_context_scores_zero():
    assert compute_groundedness("anything at all", []) == 0.0


def test_empty_answer_scores_zero():
    assert compute_groundedness("", CONTEXT) == 0.0


def test_swapped_risk_intervals_fail_local_claim_check():
    answer = (
        "High-risk customers update every eight years and medium-risk customers "
        "update every two years."
    )
    assert compute_groundedness(answer, CONTEXT) == 0.0


def test_word_and_digit_quantities_are_equivalent():
    answer = "Low-risk customers update every ten years."
    assert compute_groundedness(answer, CONTEXT) > 0.0


def test_unsupported_negation_fails_local_claim_check():
    context = [{"text": "The NBFC shall perform customer due diligence."}]
    answer = "The NBFC shall not perform customer due diligence."
    assert compute_groundedness(answer, context) == 0.0


def test_supported_negation_is_not_rejected():
    context = [{"text": "The NBFC shall not open anonymous accounts."}]
    answer = "The NBFC shall not open anonymous accounts."
    assert compute_groundedness(answer, context) > 0.8
