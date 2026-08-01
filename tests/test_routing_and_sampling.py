"""Tests for cost-aware model routing and stratified eval sampling.

Both exist because of a hard constraint hit in practice: the full 95-row eval
costs ~432k tokens against a 100k/day free-tier quota. Routing spreads load
across two model quotas; stratified sampling makes a quota-limited run a designed
measurement rather than a truncation.
"""

import collections

from app.config import settings
from app.llm import FAST_NODES, model_for
from evals.run_evals import stratified_sample

# ---- routing ----


def test_cheap_nodes_route_to_the_small_model():
    assert model_for("classify") == settings.llm_model_fast


def test_generation_is_never_routed_to_the_small_model():
    """Generation drives every scored metric; downgrading it would change what
    the evals measure, not just what they cost."""
    assert "generate" not in FAST_NODES
    assert model_for("generate") == settings.llm_model


def test_unknown_and_missing_nodes_get_the_primary_model():
    assert model_for(None) == settings.llm_model
    assert model_for("something_new") == settings.llm_model


def test_routing_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_model_fast", "")
    assert model_for("classify") == settings.llm_model


# ---- stratified sampling ----


def _rows():
    return (
        [{"difficulty": "adversarial_temporal", "question": f"t{i}"} for i in range(48)]
        + [{"difficulty": "medium", "question": f"m{i}"} for i in range(28)]
        + [{"difficulty": "out_of_scope", "question": f"o{i}"} for i in range(10)]
        + [{"difficulty": "easy", "question": f"e{i}"} for i in range(8)]
    )


def test_sample_preserves_difficulty_proportions():
    rows = _rows()
    sample = stratified_sample(rows, 24)
    got = collections.Counter(r["difficulty"] for r in sample)
    # adversarial_temporal is ~50% of the set, so it should be ~50% of the sample.
    assert got["adversarial_temporal"] >= got["medium"] > 0
    assert got["out_of_scope"] > 0, "refusal rows must not vanish from the sample"


def test_sample_returns_the_requested_size():
    assert len(stratified_sample(_rows(), 24)) == 24


def test_sample_larger_than_the_set_returns_everything_once():
    rows = _rows()
    sample = stratified_sample(rows, 500)
    assert len(sample) == len(rows)
    assert len({r["question"] for r in sample}) == len(rows), "no duplicates"


def test_sample_is_deterministic():
    rows = _rows()
    a = [r["question"] for r in stratified_sample(rows, 20)]
    b = [r["question"] for r in stratified_sample(rows, 20)]
    assert a == b, "a seeded sample must reproduce, so runs stay comparable"


def test_truncation_would_have_been_unrepresentative():
    """Documents why --sample exists: the golden set is grouped by difficulty,
    so taking the first N rows skews hard toward whatever sorts first."""
    rows = _rows()
    truncated = collections.Counter(r["difficulty"] for r in rows[:24])
    assert len(truncated) == 1, "first-N is single-difficulty — exactly the bias to avoid"
    sampled = collections.Counter(r["difficulty"] for r in stratified_sample(rows, 24))
    assert len(sampled) > 1
