"""Generation-quality metrics via LLM-as-judge (spec §14).

For a sample of golden questions, run the agent and score each answer on:
  * faithfulness  — are the answer's claims supported by the retrieved context?
  * relevancy     — does the answer actually address the question?

Caveat (stated honestly): the judge is the same Groq model that generates, so
these numbers carry self-evaluation bias. A rigorous setup uses a stronger,
independent judge validated against human scores (spec §14). This is the
lightweight, dependency-free version of the RAGAS metrics.

Run:  python -m evals.generation_metrics
"""

from __future__ import annotations

import json
import re
import time
from datetime import date
from pathlib import Path

from app.agent.graph import run_agent
from app.llm import complete
from app.retrieval.retrieve import retrieve

GOLDEN = Path("evals") / "golden_dataset.jsonl"
REPORT = Path("evals") / "reports" / "generation_metrics.md"
SAMPLE = 6
PACING_SECONDS = 4  # throttle: the free-tier LLM rate-limits a fast judge loop
# Judge with a DIFFERENT model than the generator: it has its own rate-limit quota
# and, more importantly, avoids the generator grading its own work (self-eval bias).
JUDGE_MODEL = "llama-3.1-8b-instant"

_FAITHFULNESS = (
    "You are a strict evaluator. Given CONTEXT and an ANSWER, rate how fully the "
    "answer's factual claims are supported by the context (faithfulness): 1.0 = "
    "every claim is supported, 0.0 = unsupported or contradicted. "
    'Return ONLY JSON: {"score": <0..1>, "reason": "<short>"}.'
)
_RELEVANCY = (
    "You are a strict evaluator. Given a QUESTION and an ANSWER, rate how directly "
    "the answer addresses the question: 1.0 = fully on-point, 0.0 = off-topic. "
    'Return ONLY JSON: {"score": <0..1>, "reason": "<short>"}.'
)


def _headline(avg: float, n_scored: int) -> str:
    """Never print a number when nothing was actually scored."""
    return "n/a" if n_scored == 0 else f"{avg:.2f}"


def _judge(system: str, user: str) -> float | None:
    """Return the judge's score, or None if the judge FAILED.

    Returning None (not 0.0) matters: scoring a failed call as zero silently
    poisons the average and makes the metric lie. Failures are excluded from the
    mean and reported as coverage instead.
    """
    try:
        raw = complete(system, user, max_tokens=120, model=JUDGE_MODEL)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            print(f"    judge returned no JSON: {raw[:80]!r}")
            return None
        return float(json.loads(m.group())["score"])
    except Exception as exc:
        print(f"    judge failed: {type(exc).__name__}: {str(exc)[:110]}")
        return None


def main() -> None:
    rows = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x.strip()]
    answerable = [r for r in rows if r.get("expected_doc_numbers")][:SAMPLE]

    results = []
    degraded_count = 0
    for r in answerable:
        out = run_agent(r["question"], use_cache=False)
        if out["degraded"]:
            # Generation itself failed (e.g. LLM rate limit). Judging the
            # "service unavailable" text would report 0.00 as if it were answer
            # quality — that's a lie. Mark n/a instead.
            degraded_count += 1
            print(f"    generation FAILED (not scored): {r['question'][:45]}")
            results.append({"q": r["question"], "faith": None, "rel": None})
            continue
        answer = out["answer"]
        # Reconstruct the context the answer was grounded in (child chunk texts).
        context = "\n\n".join(h["text"] for h in retrieve(r["question"], k=8, strategy="dense"))
        faith = _judge(_FAITHFULNESS, f"CONTEXT:\n{context[:6000]}\n\nANSWER:\n{answer}")
        rel = _judge(_RELEVANCY, f"QUESTION: {r['question']}\n\nANSWER:\n{answer}")
        results.append({"q": r["question"], "faith": faith, "rel": rel})
        time.sleep(PACING_SECONDS)  # stay under the free-tier rate limit

    def _mean(key: str) -> tuple[float, int]:
        vals = [x[key] for x in results if x[key] is not None]
        return (sum(vals) / len(vals) if vals else 0.0), len(vals)

    avg_faith, n_faith = _mean("faith")
    avg_rel, n_rel = _mean("rel")

    lines = [
        "# Generation-Quality Metrics (LLM-as-judge)",
        "",
        f"- Date: {date.today().isoformat()}",
        f"- Sample: {len(results)} answerable questions",
        f"- **Faithfulness: {_headline(avg_faith, n_faith)}** (scored {n_faith}/{len(results)})"
        f"  ·  **Answer relevancy: {_headline(avg_rel, n_rel)}** (scored {n_rel}/{len(results)})",
        (
            f"- ⚠️ **{degraded_count}/{len(results)} generations FAILED** (LLM rate limit) and are "
            "excluded — these numbers are not a valid quality measurement. Re-run when "
            "the quota resets."
            if degraded_count
            else "- All generations succeeded."
        ),
        f"- Judge model: `{JUDGE_MODEL}` (independent of the generator, which avoids",
        "  the generator grading its own work).",
        "- Judge failures are reported as `n/a` and EXCLUDED from the mean — scoring",
        "  a failed judge call as 0.0 would silently understate quality (this bug",
        "  produced a fake 0.67 before it was caught).",
        "- Caveat: the judge is a *smaller* model; a stronger judge validated against",
        "  human-scored answers is the rigorous path (spec §14).",
        "",
        "| Question | faithfulness | relevancy |",
        "|---|---|---|",
    ]

    def _fmt(v: float | None) -> str:
        return "n/a" if v is None else f"{v:.2f}"

    for x in results:
        lines.append(f"| {x['q'][:55]} | {_fmt(x['faith'])} | {_fmt(x['rel'])} |")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(
        f"Faithfulness={_headline(avg_faith, n_faith)} ({n_faith}/{len(results)})  "
        f"Relevancy={_headline(avg_rel, n_rel)} ({n_rel}/{len(results)}) -> {REPORT}"
    )


if __name__ == "__main__":
    main()
