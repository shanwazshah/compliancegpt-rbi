# ADR 0007 — Metrics that can fail

**Status:** Accepted
**Date:** 2026-08-01

## Context

This project reports numbers: retrieval recall, citation accuracy, temporal
correctness, generation faithfulness, cost per query. Those numbers are the whole
argument that the system works. Two incidents while building the eval harness
showed how easily a metric becomes decorative — high, stable, and meaningless.

**Incident 1 — failures scored as zeros.** The generation-quality harness called
an LLM judge per answer. When a judge call failed (Groq rate limit), the code
recorded `0.0` and averaged it in. A run where 4 of 6 judge calls failed reported
**faithfulness 0.67**, which read as "the system is mediocre" when the truth was
"we measured almost nothing." The fix was to record failures as `n/a` and exclude
them from the mean. The corrected run reported `0.00 (0/6 scored)` with an
explicit warning — an obviously broken measurement instead of a plausible bad one.

**Incident 2 — a metric that could not fail.** The golden set had exactly one
`adversarial_temporal` row, and that row asserted nothing checkable: it expected
no documents and listed no document that must not be cited. Any answer citing
nothing would score as a pass, including an answer that simply failed to retrieve.
"Temporal correctness" computed over that row would have been a number that no
incorrect system could lose points on.

The pattern behind both: **a metric is only worth reporting if there is a
realistic way for it to come out badly.**

## Decision

Four rules, enforced in code rather than by convention.

### 1. "Not measured" is `None`, never `0.0`

`MetricResult.value` returns `None` when nothing was scorable
(`evals/project_metrics.py`). This propagates all the way out: `null` in
`latest_metrics.json`, `NULL` in `eval_runs`, `n/a (not measured)` in the report,
and `None` (not `0.0`) for cost when a model's price is unknown
(`app/observability/cost.py`).

The CI gate treats the two differently and is tested on exactly that
(`tests/test_eval_gate.py::test_zero_is_enforced_even_though_it_is_falsy`): a
measured `0.0` fails the build, an unmeasured `None` skips. A naive `if not
value` check would conflate them and let a total failure through — which is the
specific bug this rule exists to prevent.

### 2. A row that cannot fail is not scored

Every `adversarial_temporal` row must carry `must_not_cite`, and rows without it
return `None` from the scorer rather than a free pass. The golden-set test suite
rejects a temporal row that has no date or nothing it forbids
(`tests/test_golden_dataset.py::test_every_temporal_row_is_date_scoped_and_falsifiable`).

### 3. Errors are excluded, not counted as failures

If the agent raises while evaluating a row, that row is dropped from the
denominator and the exclusion count is printed. An outage is not a quality
signal. This mirrors rule 1 in the opposite direction: just as a failed
measurement must not become a zero, an infrastructure failure must not become a
recorded regression.

### 4. Metric definitions are pure functions with unit tests

The scorers take plain data and return plain results — no database, no LLM, no
network (`evals/project_metrics.py`, tested in `tests/test_project_metrics.py`).
A reader can check the definition against spec §14 without running the system,
and a change that quietly weakens a definition breaks a test.

## Consequences

**We report worse-looking numbers.** `faithfulness: n/a` is less impressive than
`0.67`, and a `None` cost is less impressive than `$0.0000`. Both are honest, and
the failure mode they prevent — a confident number nobody can reproduce — is the
one that does real damage.

**Some metrics are scoped by what the corpus can support.** Temporal correctness
is scored as "cited nothing that was not in force at the reference date," not
"retrieved the historical document." The withdrawn predecessors are in the
supersession graph, but their PDFs are not chunked or embedded, so no retriever
could return them; scoring on retrieval would report a flat 0% that measures
corpus coverage rather than temporal reasoning. The narrower definition is the
one spec §14 actually states, and the report says plainly which one is in use.

**Thresholds sit below measured values, not at them.** A floor pinned to the
current number turns run-to-run variance into red builds, and a gate that cries
wolf gets ignored — at which point the gate is worse than none, because it looks
like coverage.

## Related

- [ADR 0002](0002-why-hybrid-retrieval.md) — why the honest ablation result
  (dense beating hybrid+rerank on this corpus) is reported and shipped as the
  default, rather than shipping the fancier pipeline anyway.
