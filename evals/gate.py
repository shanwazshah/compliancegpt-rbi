"""Eval gate: fail the build when a golden-set metric regresses (spec §19, Phase 3).

Compares `evals/reports/latest_metrics.json` against the floors committed in
`evals/thresholds.json` and exits non-zero on any regression. This is what makes
"eval-gated CI" a real gate rather than a claim.

Three outcomes, deliberately distinguished:

  * **PASS**  — every enforced metric is at or above its floor.
  * **FAIL**  — a measured metric dropped below its floor. Exit 1.
  * **SKIP**  — the metric was not measured (null in the results). Reported, not
    enforced. A build must not go red because an eval could not run against a
    corpus; that is an infrastructure failure, not a quality regression, and
    conflating the two is how teams learn to ignore a red gate.

A metric that is `null` in thresholds.json is not enforced at all — that is the
knob for "we don't have a trustworthy baseline for this yet".

Run:  python -m evals.gate
      python -m evals.gate --metrics path/to/metrics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THRESHOLDS = Path("evals") / "thresholds.json"
METRICS = Path("evals") / "reports" / "latest_metrics.json"


def load_thresholds(path: Path = THRESHOLDS) -> dict[str, float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_") and v is not None}


def evaluate(metrics: dict, thresholds: dict[str, float]) -> tuple[list[str], list[str], list[str]]:
    """Return (failures, passes, skips) as human-readable lines."""
    failures, passes, skips = [], [], []
    for name, floor in sorted(thresholds.items()):
        value = metrics.get(name)
        if value is None:
            skips.append(f"{name}: not measured (floor {floor:.1%}) — not enforced")
            continue
        if value < floor:
            failures.append(
                f"{name}: {value:.1%} is below the floor of {floor:.1%} "
                f"(regression of {(floor - value) * 100:.1f} points)"
            )
        else:
            passes.append(f"{name}: {value:.1%} >= {floor:.1%}")
    return failures, passes, skips


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metrics", type=Path, default=METRICS)
    ap.add_argument("--thresholds", type=Path, default=THRESHOLDS)
    args = ap.parse_args(argv)

    if not args.metrics.exists():
        print(
            f"No metrics at {args.metrics} — run `python -m evals.run_evals` first.\n"
            "Skipping the gate rather than failing: absent results mean the eval did "
            "not run, which is not a quality regression."
        )
        return 0

    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    thresholds = load_thresholds(args.thresholds)
    failures, passes, skips = evaluate(metrics, thresholds)

    print(f"Eval gate — commit {(metrics.get('git_commit_sha') or 'unknown')[:12]}")
    for line in passes:
        print(f"  PASS  {line}")
    for line in skips:
        print(f"  SKIP  {line}")
    for line in failures:
        print(f"  FAIL  {line}")

    if failures:
        print(f"\n{len(failures)} metric(s) regressed below the committed floor.")
        print("Fix the regression, or raise/lower the floor deliberately in evals/thresholds.json.")
        return 1
    print("\nAll enforced metrics are at or above their floors.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
