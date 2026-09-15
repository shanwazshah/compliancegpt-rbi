# Advanced local retrieval pilot — 2026-09-14

This is a development-set retrieval benchmark over 15 manually checked physical-page
locations in five RBI NBFC Master Directions. It measures document retrieval, physical
page retrieval and immutable evidence-ID resolution. It does not measure legal answer
correctness, claim entailment, exception completeness or historical-version coverage.

The ranking and local PageIndex logic were tuned after inspecting misses on this same
dataset. These results verify the implementation but are not evidence of generalisation;
an independently reviewed holdout is still required.

## Reproducibility

- Dataset: `evals/advanced_pilot.jsonl`
- Dataset SHA-256: `7b39c5b57ebadcd27466ebe2402d31db0c801b393fec2d3832820aa8616d43be`
- Corpus evidence revision: `437`
- K: 8; maximum candidate documents: 5; navigated document trees: 1
- Navigation: deterministic local lexical anchors plus PageIndex section metadata
- Evidence storage: PostgreSQL with migration 0008 stored `tsvector` and GIN index
- Runtime: local Windows host, warm PostgreSQL Docker container, IPv4 loopback

## Results

| Route | Document recall@8 | Physical-page recall@8 | Evidence resolution | Mean | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 15/15 (100%) | 12/15 (80%) | 120/120 (100%) | 82.85 ms | 73.97 ms | 112.70 ms |
| pageindex (local) | 15/15 (100%) | 15/15 (100%) | 120/120 (100%) | 77.98 ms | 82.33 ms | 121.01 ms |
| graph_pageindex (local) | 15/15 (100%) | 15/15 (100%) | 120/120 (100%) | 95.86 ms | 92.62 ms | 122.39 ms |

Lexical retrieval missed the checked pages for `registration-net-owned-fund` (page 21),
`registration-upper-layer-size` (page 14), and `amalgamation-scope` (page 3). Local
PageIndex recovered all three by expanding the strongest page anchor within the stored
section boundaries and ranking matching section titles/summaries.

The graph route has no measured lift over PageIndex yet. The two extracted KYC graph
relations are candidates and are intentionally excluded until human review. This result
therefore validates review-state isolation, not knowledge-graph quality.

## Frozen internal holdout

After the implementation above was frozen, a second dataset was created from ten different
source locations and run once. No retrieval changes were made after seeing these results.
The locations were checked by the implementer, not by an independent regulatory reviewer.

- Dataset: `evals/advanced_holdout.jsonl`
- Dataset SHA-256: `cf89b0aa0b79a43803165b693efe4fae6910dff22826fe9294ab96336810c5a6`
- Corpus evidence revision: `437`

| Route | Document recall@8 | Physical-page recall@8 | Evidence resolution | Mean | p50 | p95 |
|---|---:|---:|---:|---:|---:|---:|
| lexical | 10/10 (100%) | 9/10 (90%) | 80/80 (100%) | 86.06 ms | 87.36 ms | 108.86 ms |
| pageindex (local) | 10/10 (100%) | 9/10 (90%) | 78/78 (100%) | 88.06 ms | 88.67 ms | 99.86 ms |
| graph_pageindex (local) | 10/10 (100%) | 9/10 (90%) | 78/78 (100%) | 99.42 ms | 102.22 ms | 131.34 ms |

All routes missed `holdout-kyc-onboarding-rejection`: the checked rule is on physical page
20. Local PageIndex returned adjacent physical page 19 but not page 20. The miss is retained
as evidence that the development-set 15/15 does not establish complete page retrieval.

## Reproduce

```powershell
python -m ingestion.migrate
python -m evals.advanced_retrieval --strategy lexical --k 8 --output data/evals/advanced_lexical.json
python -m evals.advanced_retrieval --strategy pageindex --k 8 --output data/evals/advanced_pageindex.json
python -m evals.advanced_retrieval --strategy graph_pageindex --k 8 --output data/evals/advanced_graph_pageindex.json
python -m evals.advanced_retrieval --dataset evals/advanced_holdout.jsonl --strategy pageindex --k 8 --output data/evals/advanced_holdout_pageindex.json
```

Raw reports remain local under `data/evals/` because `data/` is excluded from version
control. Each raw report contains every retrieved document, physical page, evidence ID,
resolution result, latency and error.
