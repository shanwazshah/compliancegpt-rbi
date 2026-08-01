"""Golden-set eval: retrieval metrics + the three project metrics (spec §14).

Produces three artifacts:
  * `evals/reports/golden_set_eval.md` — the human-readable report
  * `evals/reports/latest_metrics.json` — machine-readable, consumed by the CI gate
  * a row in `eval_runs` — the eval history the API exposes at /api/eval/latest

Metrics that could not be computed are recorded as `null`, never 0.0. A metric
recorded as zero is a claim that the system failed every case; a metric recorded
as null is a claim that we did not measure it. CI treats them differently (see
evals/gate.py), and so should a reader.

Run:  python -m evals.run_evals                 # retrieval + end-to-end
      python -m evals.run_evals --retrieval-only  # no LLM calls
      python -m evals.run_evals --limit 20        # cap end-to-end rows
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from app.retrieval.retrieve import retrieve
from evals.project_metrics import score_all

GOLDEN = Path("evals") / "golden_dataset.jsonl"
REPORT_DIR = Path("evals") / "reports"
METRICS_JSON = REPORT_DIR / "latest_metrics.json"
K = 5
DEFAULT_STRATEGY = "dense"      # the measured-best strategy (see ablation report)

# Below this share of scorable rows, the project metrics are reported as NOT
# MEASURED instead of being computed over whatever survived.
MIN_SCORED_FRACTION = 0.5


def load_golden() -> list[dict]:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _known_doc_numbers() -> set[str] | None:
    """Every doc_number in the corpus, so a hallucinated citation is detectable."""
    try:
        from app.db.queries import get_connection, list_documents

        with get_connection() as conn:
            return {d["doc_number"] for d in list_documents(conn)}
    except Exception:
        return None      # can't verify realness; citation accuracy still scores expectedness


def retrieval_metrics(rows: list[dict], strategy: str = DEFAULT_STRATEGY) -> dict:
    """Recall@K and MRR over rows that expect at least one document."""
    answerable = [r for r in rows if r.get("expected_doc_numbers")]
    hits = 0
    rr = 0.0
    details = []
    for r in answerable:
        expected = set(r["expected_doc_numbers"])
        results = retrieve(r["question"], k=K, strategy=strategy)
        ranked = [h["doc_number"] for h in results]
        rank = next((i for i, dn in enumerate(ranked, 1) if dn in expected), None)
        if rank:
            hits += 1
            rr += 1.0 / rank
        details.append(
            {
                "question": r["question"],
                "expected": sorted(expected),
                "rank": rank,
                "top": ranked[0] if ranked else None,
            }
        )
    n = len(answerable)
    return {
        "recall_at_k": (hits / n) if n else None,
        "mrr": (rr / n) if n else None,
        "n": n,
        "details": details,
    }


def stratified_sample(rows: list[dict], n: int, seed: int = 20260801) -> list[dict]:
    """Take `n` rows keeping each difficulty's share of the set.

    A quota-limited run should be a *designed sample*, not a truncation. Taking
    the first N rows would over-weight whatever happens to sort first — the
    golden set is grouped by difficulty, so `[:22]` is almost all one kind of
    question. Sampling proportionally means the reported metric is a real
    estimate over the whole set, and the row count is stated alongside it.
    """
    import collections
    import random

    rng = random.Random(seed)
    by_difficulty: dict[str, list[dict]] = collections.defaultdict(list)
    for r in rows:
        by_difficulty[r["difficulty"]].append(r)

    picked: list[dict] = []
    for difficulty, group in sorted(by_difficulty.items()):
        share = max(1, round(n * len(group) / len(rows)))
        picked.extend(rng.sample(group, min(share, len(group))))
    rng.shuffle(picked)
    return picked[:n]


def end_to_end(rows: list[dict], limit: int | None = None, sample: int | None = None) -> list[dict]:
    """Run the full agent over the golden set and collect what it cited."""
    from app.agent.graph import run_agent

    scored = [
        r
        for r in rows
        if r["difficulty"] in ("adversarial_temporal", "out_of_scope")
        or r.get("expected_doc_numbers")
    ]
    if sample:
        scored = stratified_sample(scored, sample)
    elif limit:
        scored = scored[:limit]

    results = []
    for i, r in enumerate(scored, 1):
        try:
            # Cache off: a cache hit would score a stale answer, not this build's.
            out = run_agent(r["question"], r.get("reference_date"), use_cache=False)
            # A DEGRADED answer is an outage, not an answer. The agent catches
            # LLM failures and returns degraded=True rather than raising (spec
            # §15 graceful degradation), so without this check a total LLM outage
            # scores as a perfect run: nothing is cited, so every "must not cite"
            # row trivially passes and temporal correctness reads 100%.
            # That actually happened — see docs/adr/0007.
            if out.get("degraded"):
                raise RuntimeError(
                    "generation degraded (LLM unavailable) — not a scorable answer"
                )
            results.append(
                {
                    "row": r,
                    "cited": [c["doc_number"] for c in out.get("citations", [])],
                    "answer": out.get("answer", ""),
                    "degraded": False,
                }
            )
        except Exception as exc:  # noqa: BLE001
            # A failed run is NOT a scored failure — record it and exclude it,
            # the same rule the generation-metrics harness applies to failed
            # judge calls (docs/adr/0007).
            print(f"  ! [{i}/{len(scored)}] run failed ({type(exc).__name__}) — excluded")
            results.append({"row": r, "cited": [], "answer": "", "error": str(exc)})
        if i % 10 == 0:
            print(f"  [{i}/{len(scored)}] evaluated")
    return results


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--retrieval-only", action="store_true", help="skip LLM calls")
    ap.add_argument("--limit", type=int, default=None, help="cap end-to-end rows (truncates)")
    ap.add_argument(
        "--sample",
        type=int,
        default=None,
        help="score a stratified sample of N rows (preferred over --limit when quota-bound)",
    )
    ap.add_argument("--strategy", default=DEFAULT_STRATEGY)
    args = ap.parse_args(argv)

    rows = load_golden()
    print(f"Golden set: {len(rows)} rows")

    retrieval = retrieval_metrics(rows, strategy=args.strategy)
    recall = retrieval["recall_at_k"]
    print(f"Recall@{K}={'n/a' if recall is None else format(recall, '.1%')}")

    metrics = {
        "citation_accuracy": None,
        "temporal_correctness": None,
        "refusal_correctness": None,
    }
    scored = {}
    ok_results: list[dict] = []
    if not args.retrieval_only:
        results = end_to_end(rows, limit=args.limit, sample=args.sample)
        ok_results = [r for r in results if "error" not in r]
        excluded = len(results) - len(ok_results)
        if excluded:
            print(f"  {excluded} row(s) excluded: the agent errored, so they were not scored")

        # Refuse to report metrics computed on a rump of surviving rows. A number
        # from 4 of 95 rows is not a smaller measurement of the same thing — it is
        # a different, unrepresentative one, and it will be read as the headline.
        fraction = len(ok_results) / len(results) if results else 0.0
        if fraction < MIN_SCORED_FRACTION:
            print(
                f"\n  !! Only {len(ok_results)}/{len(results)} rows produced a scorable "
                f"answer ({fraction:.0%}). Reporting the project metrics as NOT MEASURED "
                "rather than computing them over the survivors.\n"
                "     Check the LLM provider/key, then re-run."
            )
            scored = {}
        else:
            scored = score_all(ok_results, known_doc_numbers=_known_doc_numbers())
            metrics = {name: m.value for name, m in scored.items()}

    payload = {
        "date": date.today().isoformat(),
        "git_commit_sha": _git_sha(),
        "strategy": args.strategy,
        "golden_set_size": len(rows),
        "scored_rows": len(ok_results),
        "recall_at_5": retrieval["recall_at_k"],
        "mrr": retrieval["mrr"],
        **metrics,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_report(rows, retrieval, scored, payload)
    _record_eval_run(payload)

    print("\n" + json.dumps(payload, indent=2))
    print(f"Wrote {METRICS_JSON}")


def _write_report(rows: list[dict], retrieval: dict, scored: dict, payload: dict) -> None:
    import collections

    by_difficulty = collections.Counter(r["difficulty"] for r in rows)
    by_source = collections.Counter(r.get("source", "unknown") for r in rows)

    def pct(v):
        return "n/a (not measured)" if v is None else f"{v:.1%}"

    def num(v):
        return "n/a (not measured)" if v is None else f"{v:.3f}"

    lines = [
        "# Golden-Set Eval",
        "",
        f"- Date: {payload['date']}",
        f"- Commit: `{(payload['git_commit_sha'] or 'unknown')[:12]}`",
        f"- Retrieval strategy: {payload['strategy']}",
        f"- Golden set: {payload['golden_set_size']} rows "
        f"({dict(by_difficulty)})",
        f"- Row provenance: {dict(by_source)}",
        "",
        "## Headline metrics (spec §14)",
        "",
        "| Metric | Value | Scored over |",
        "|---|---|---|",
        f"| Citation accuracy | {pct(payload['citation_accuracy'])} | "
        f"{scored['citation_accuracy'].total if scored else 0} citations |",
        f"| Temporal correctness | {pct(payload['temporal_correctness'])} | "
        f"{scored['temporal_correctness'].total if scored else 0} date-scoped rows |",
        f"| Refusal correctness | {pct(payload['refusal_correctness'])} | "
        f"{scored['refusal_correctness'].total if scored else 0} out-of-scope rows |",
        f"| Recall@{K} | {pct(payload['recall_at_5'])} | {retrieval['n']} answerable rows |",
        f"| MRR | {num(payload['mrr'])} | {retrieval['n']} answerable rows |",
        "",
        "## How temporal correctness is scored",
        "",
        "A date-scoped row passes when the answer cites **no document that was not in",
        "force at the reference date**. It is not required to cite the historical",
        "document: the withdrawn predecessors are in the supersession graph, but their",
        "PDFs are not chunked or embedded, so no retriever could return them. Scoring on",
        '"did it find the old circular" would report a flat 0% that measures corpus',
        "coverage rather than temporal reasoning.",
        "",
    ]

    if scored:
        for name in ("temporal_correctness", "refusal_correctness"):
            m = scored[name]
            if m.failures:
                lines += [f"### {name} — failures ({len(m.failures)})", ""]
                lines += [f"- {f}" for f in m.failures[:15]]
                lines += [""]

    lines += [
        "## Per-question retrieval rank",
        "",
        "| Question | Expected | Rank |",
        "|---|---|---|",
    ]
    for d in retrieval["details"]:
        lines.append(
            f"| {d['question'][:58]} | {', '.join(d['expected'])} | "
            f"{d['rank'] if d['rank'] else 'MISS'} |"
        )

    (REPORT_DIR / "golden_set_eval.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record_eval_run(payload: dict) -> None:
    """Persist to eval_runs. Never fails the eval over a logging problem."""
    try:
        from app.db.queries import get_connection, insert_eval_run

        with get_connection() as conn:
            insert_eval_run(
                conn,
                {
                    "git_commit_sha": payload["git_commit_sha"],
                    "retrieval_strategy": payload["strategy"],
                    "golden_set_size": payload["golden_set_size"],
                    "recall_at_5": payload["recall_at_5"],
                    "mrr": payload["mrr"],
                    "citation_accuracy": payload["citation_accuracy"],
                    "temporal_correctness": payload["temporal_correctness"],
                    "refusal_correctness": payload["refusal_correctness"],
                    "raw_results_path": str(METRICS_JSON),
                },
            )
        print("Recorded eval_runs row.")
    except Exception as exc:  # noqa: BLE001
        print(f"(could not record eval_runs row: {type(exc).__name__}: {exc})")


if __name__ == "__main__":
    main(sys.argv[1:])
