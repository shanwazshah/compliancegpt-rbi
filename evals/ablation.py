"""Retrieval ablation: dense vs BM25 vs hybrid.

Computes Recall@K and MRR for each strategy over the golden set's answerable
rows, and writes a comparison table to evals/reports/. This is the evidence for
the README's "why hybrid" claim (spec §13). The rerank column is added once the
reranker lands.

Run:  python -m evals.ablation
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from app.retrieval.retrieve import retrieve

GOLDEN = Path("evals") / "golden_dataset.jsonl"
REPORT = Path("evals") / "reports" / "ablation_retrieval.md"
K = 5
STRATEGIES = ("dense", "bm25", "hybrid", "hybrid_rerank")


def _answerable() -> list[dict]:
    rows = [json.loads(x) for x in GOLDEN.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("expected_doc_numbers")]


def _metrics(rows: list[dict], strategy: str) -> tuple[float, float, list[int | None]]:
    hits = 0
    rr = 0.0
    ranks: list[int | None] = []
    for r in rows:
        expected = set(r["expected_doc_numbers"])
        ranked = [h["doc_number"] for h in retrieve(r["question"], k=K, strategy=strategy)]
        rank = next((i for i, dn in enumerate(ranked, 1) if dn in expected), None)
        ranks.append(rank)
        if rank:
            hits += 1
            rr += 1.0 / rank
    n = len(rows)
    return hits / n, rr / n, ranks


def main() -> None:
    rows = _answerable()
    results = {s: _metrics(rows, s) for s in STRATEGIES}

    lines = [
        "# Retrieval Ablation — dense vs BM25 vs hybrid vs hybrid+rerank",
        "",
        f"- Date: {date.today().isoformat()}",
        f"- Golden set: {len(rows)} answerable questions · K={K}",
        "",
        f"| Strategy | Recall@{K} | MRR |",
        "|---|---|---|",
    ]
    for s in STRATEGIES:
        recall, mrr, _ = results[s]
        lines.append(f"| {s} | {recall:.1%} | {mrr:.3f} |")

    # Per-question ranks, to see exactly which strategy rescued which question.
    lines += ["", f"## Per-question rank of the expected doc (K={K}, MISS = not in top {K})", ""]
    lines.append("| Question | " + " | ".join(STRATEGIES) + " |")
    lines.append("|---|" + "|".join(["---"] * len(STRATEGIES)) + "|")
    for i, r in enumerate(rows):
        cells = []
        for s in STRATEGIES:
            rank = results[s][2][i]
            cells.append(str(rank) if rank else "MISS")
        lines.append(f"| {r['question'][:55]} | " + " | ".join(cells) + " |")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    for s in STRATEGIES:
        recall, mrr, _ = results[s]
        print(f"{s:8}  Recall@{K}={recall:.1%}  MRR={mrr:.3f}")
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    main()
