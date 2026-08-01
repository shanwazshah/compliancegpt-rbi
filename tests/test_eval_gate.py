"""Tests for the CI eval gate.

The gate's whole value is that it fails builds, so its pass/fail/skip logic is
tested directly — a gate that silently passes everything is worse than no gate,
because it looks like coverage.
"""

import json

from evals.gate import evaluate, load_thresholds, main


def test_regression_below_floor_fails():
    failures, passes, skips = evaluate({"recall_at_5": 0.80}, {"recall_at_5": 0.85})
    assert failures and not passes
    assert "below the floor" in failures[0]


def test_metric_at_the_floor_passes():
    failures, passes, _ = evaluate({"recall_at_5": 0.85}, {"recall_at_5": 0.85})
    assert passes and not failures


def test_unmeasured_metric_is_skipped_not_failed():
    # An eval that could not run is an infrastructure problem, not a quality
    # regression — it must not turn the build red.
    failures, passes, skips = evaluate({"recall_at_5": None}, {"recall_at_5": 0.85})
    assert skips and not failures and not passes


def test_zero_is_enforced_even_though_it_is_falsy():
    # 0.0 means "measured, everything failed" and MUST fail the gate; a naive
    # `if not value` check would treat it as unmeasured and let it through.
    failures, _, skips = evaluate({"temporal_correctness": 0.0}, {"temporal_correctness": 0.5})
    assert failures and not skips


def test_null_threshold_is_not_enforced(tmp_path):
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps({"_comment": "x", "recall_at_5": 0.85, "temporal_correctness": None})
    )
    loaded = load_thresholds(path)
    assert loaded == {"recall_at_5": 0.85}


def test_missing_metrics_file_skips_rather_than_fails(tmp_path, capsys):
    rc = main(["--metrics", str(tmp_path / "nope.json")])
    assert rc == 0
    assert "Skipping the gate" in capsys.readouterr().out


def test_gate_exit_codes(tmp_path):
    thresholds = tmp_path / "t.json"
    thresholds.write_text(json.dumps({"recall_at_5": 0.85}))

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"recall_at_5": 0.92, "git_commit_sha": "abc123"}))
    assert main(["--metrics", str(good), "--thresholds", str(thresholds)]) == 0

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"recall_at_5": 0.42, "git_commit_sha": "abc123"}))
    assert main(["--metrics", str(bad), "--thresholds", str(thresholds)]) == 1


def test_committed_thresholds_are_loadable():
    """The repo's own thresholds file must stay parseable and sane."""
    loaded = load_thresholds()
    assert loaded, "no enforced thresholds — the gate would be a no-op"
    for name, floor in loaded.items():
        assert 0.0 <= floor <= 1.0, f"{name} floor out of range: {floor}"
