"""Phase 1 manual eval pass.

Measures two things over the golden set:
  1. Retrieval quality (cheap, no LLM): Recall@5 and MRR over answerable rows —
     does dense search surface the expected document in the top 5?
  2. End-to-end generation on a small sample: does the answer cite the expected
     document, and are out-of-scope questions handled?

Writes a Markdown report to evals/reports/. This is the Phase 1 eval deliverable;
the full RAGAS + ablation harness arrives in Phase 2.

Run:  python -m evals.run_evals
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.agent.pipeline import answer_query
from app.retrieval.retrieve import retrieve

GOLDEN = Path("evals") / "golden_dataset.jsonl"
REPORT_DIR = Path("evals") / "reports"
K = 5
GEN_SAMPLE = 4  # how many rows to run full generation on (limits LLM calls)


def _load_golden() -> list[dict]:
    lines = GOLDEN.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _answerable_rows(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r.get("expected_doc_numbers")]


def _retrieval_metrics(rows: list[dict]) -> tuple[float, float, list[dict]]:
    """Recall@K and MRR over rows that expect at least one document."""
    answerable = _answerable_rows(rows)
    hits = 0
    reciprocal_ranks = 0.0
    details = []
    for r in answerable:
        expected = set(r["expected_doc_numbers"])
        results = retrieve(r["question"], k=K, strategy="hybrid")
        ranked = [h["doc_number"] for h in results]
        rank = next((i for i, dn in enumerate(ranked, 1) if dn in expected), None)
        if rank:
            hits += 1
            reciprocal_ranks += 1.0 / rank
        details.append(
            {
                "question": r["question"],
                "expected": sorted(expected),
                "rank": rank,
                "top": ranked[0],
            }
        )
    n = len(answerable)
    return (hits / n if n else 0.0), (reciprocal_ranks / n if n else 0.0), details


def main() -> None:
    rows = _load_golden()
    recall, mrr, details = _retrieval_metrics(rows)

    # End-to-end generation on a sample (a few answerable + the refusals).
    answerable = [r for r in rows if r.get("expected_doc_numbers")][:GEN_SAMPLE]
    refusals = [r for r in rows if r.get("difficulty") == "out_of_scope"][:2]
    gen_results = []
    for r in answerable + refusals:
        out = answer_query(r["question"])
        cited = [c["doc_number"] for c in out["citations"]]
        expected = set(r.get("expected_doc_numbers") or [])
        gen_results.append(
            {
                "question": r["question"],
                "category": r.get("category"),
                "expected": sorted(expected),
                "cited": cited,
                "citation_ok": (bool(expected) and bool(expected & set(cited)))
                or (not expected),  # refusals: ok if it cited nothing
                "answer": out["answer"],
                "degraded": out["degraded"],
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / "phase1_manual_eval.md"
    lines = [
        "# Phase 1 — Manual Eval Report",
        "",
        f"- Date: {date.today().isoformat()}",
        "- Strategy: hybrid retrieval (bge-small-en-v1.5 + BM25) + Groq llama-3.3-70b generation",
        f"- Golden set: {len(rows)} rows ({len(_answerable_rows(rows))} answerable)",
        "",
        "## Retrieval metrics (answerable rows)",
        "",
        f"- **Recall@{K}: {recall:.1%}**  (expected doc appears in top {K})",
        f"- **MRR: {mrr:.3f}**",
        "",
        "| Question | Expected | Rank | Top-1 |",
        "|---|---|---|---|",
    ]
    for d in details:
        rank = str(d["rank"]) if d["rank"] else "MISS"
        lines.append(f"| {d['question'][:60]} | {', '.join(d['expected'])} | {rank} | {d['top']} |")

    lines += ["", "## End-to-end generation sample", ""]
    for g in gen_results:
        mark = "✅" if g["citation_ok"] else "❌"
        lines.append(f"### {mark} {g['question']}")
        exp = g["expected"] or "(none — refusal expected)"
        lines.append(f"- expected: {exp} · cited: {g['cited'] or '(none)'}")
        lines.append(f"- answer: {g['answer'][:400]}")
        lines.append("")

    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"Recall@{K}={recall:.1%}  MRR={mrr:.3f}  ({len(details)} answerable rows)")
    print(f"Wrote {report}")


if __name__ == "__main__":
    main()
