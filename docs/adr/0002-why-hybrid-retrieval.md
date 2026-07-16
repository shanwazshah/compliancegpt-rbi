# ADR 0002 — Retrieval: hybrid (dense + BM25 + rerank), but default to dense

- Status: Accepted (evidence-driven)
- Date: 2026-07-16

## Context

Dense (semantic) search can miss precise terminology and regulation identifiers
(e.g. "capital adequacy", `DBR.No.BP.BC.99`). BM25 (lexical) is strong exactly
there. The plan was hybrid retrieval (RRF fusion) + cross-encoder reranking.

## Decision

Implement **dense, BM25, hybrid (RRF), and hybrid+rerank** strategies behind one
`retrieve(strategy=...)` dispatcher, run a **4-way ablation** on the golden set,
and let the measured result choose the default — which turned out to be **dense**.

## Rationale (the honest result)

Ablation on the 30-question golden set (`evals/reports/ablation_retrieval.md`):

| strategy | Recall@5 | MRR |
|---|---|---|
| dense | 92.3% | 0.811 |
| bm25 | 92.3% | 0.655 |
| hybrid | 92.3% | 0.728 |
| hybrid+rerank | 88.5% | 0.735 |

On this clean corpus (each document is a distinct topic) dense is already
near-ceiling. BM25 *individually* rescued both of dense's misses, and the
reranker pulled one from unranked to rank 1 — proving the mechanism — but naive
RRF rewards cross-retriever agreement, and the small out-of-domain reranker
misjudged two legal queries. Net: dense wins in aggregate here.

## Consequences

- Default strategy = `dense`; the advanced strategies remain available and
  ablated. We report the real numbers rather than assuming the fancy pipeline
  wins (spec §3).
- Expected to change with (a) a golden set that includes identifier queries, and
  (b) the intended larger models (bge-m3, bge-reranker-v2-m3) on better hardware.
