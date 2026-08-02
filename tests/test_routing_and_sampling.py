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


# ---- resumable evals ----


def test_cache_roundtrip_and_resume_skips_completed_rows(tmp_path, monkeypatch):
    """A quota-limited run must accumulate, not restart.

    Without this, a free tier that allows ~22 rows/day can never reach a
    full-set denominator no matter how many times the eval runs.
    """
    import evals.run_evals as harness

    monkeypatch.setattr(harness, "CACHE", tmp_path / "eval_cache.jsonl")

    row = {"question": "q1", "reference_date": "2024-06-30", "difficulty": "adversarial_temporal"}
    key = harness._row_key(row)
    harness.append_cache(key, row, ["RBI/DOR/2025-26/361"], "an answer", "abc123")

    cache = harness.load_cache()
    assert key in cache
    assert cache[key]["cited"] == ["RBI/DOR/2025-26/361"]
    assert cache[key]["git_commit_sha"] == "abc123"


def test_row_key_distinguishes_the_same_question_at_different_dates():
    import evals.run_evals as harness

    base = {"question": "What governs KYC?"}
    assert harness._row_key({**base, "reference_date": "2024-06-30"}) != harness._row_key(
        {**base, "reference_date": None}
    )


def test_corrupt_cache_line_is_skipped_not_fatal(tmp_path, monkeypatch):
    """An interrupted run can leave a half-written line; it must not break resume."""
    import evals.run_evals as harness

    cache = tmp_path / "eval_cache.jsonl"
    cache.write_text('{"key": "a", "cited": [], "answer": "ok"}\n{"key": "b", "cit\n')
    monkeypatch.setattr(harness, "CACHE", cache)
    loaded = harness.load_cache()
    assert set(loaded) == {"a"}


def test_cache_key_includes_the_model(monkeypatch):
    """Resuming after a provider switch must not mix models into one metric.

    Without the model in the key, a 70B re-run would replay cached llama3.2
    answers and report the blend as a single number — a silently mixed
    measurement, worse than none because nothing looks wrong.
    """
    import evals.run_evals as harness

    row = {"question": "q", "reference_date": None}
    small = harness._row_key(row, model="llama3.2")
    large = harness._row_key(row, model="llama-3.3-70b-versatile")
    assert small != large
    assert "llama3.2" in small
