"""The three project-specific metrics from spec §14.

These are the numbers that differentiate this project from a generic RAG demo,
so the scoring rules are written here as **pure functions** — no database, no
LLM, no network. That means they are unit-tested directly (tests/test_project_metrics.py)
and a reader can check the definition against the spec without running anything.

    citation_accuracy    — % of cited document numbers that are real and expected
    temporal_correctness — % of date-scoped questions answered only from documents
                           in force at that date
    refusal_correctness  — % of out-of-scope questions correctly declined

## The scoring rule that matters

`temporal_correctness` is defined negatively, exactly as spec §14 phrases it
("answered from documents actually in force at that date"). A date-scoped answer
is correct when it cites **nothing that was not in force** at the reference date.
It is not required to cite the historical document: those predecessors are in the
supersession graph but their text is not in the vector index, so no retriever
could return them. Scoring on "did it find the old circular" would report a flat
0% that measures corpus coverage, not temporal reasoning — see
evals/reports/ for the caveat that ships with the number.

A row is only scored when it can actually fail: `must_not_cite` must be
non-empty, which the golden-set tests enforce.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Phrases that indicate the system declined rather than answered. Kept explicit
# (and matched case-insensitively) so the refusal check is auditable rather than
# a fuzzy judgement call.
#
# POST-HOC CORRECTION (2026-08-01). The first version of this list was written
# from imagination before any answers existed, and it under-counted refusals:
# a run scored 30% where three of the seven "failures" were unambiguous declines
# the list simply did not recognise — "does not provide information about…",
# "I do not have access to that information.", "I can't provide financial
# advice…". Corrected to 60%.
#
# Editing a scorer after seeing results is exactly how a metric gets quietly
# inflated, so the bar applied here was: add a phrase only if it is a decline on
# its face, independent of whether it helps the score. Phrases that merely sound
# unconfident while still asserting a regulatory fact were NOT added — the model
# answering "the minimum capital requirement for a Payments Bank is ₹500 crores"
# with no source is still a failure, and still counts as one.
REFUSAL_MARKERS = (
    "outside the scope",
    "out of scope",
    "does not contain",
    "do not have enough information",
    "not enough information",
    "no relevant source",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "not in force",
    "no document in force",
    # --- added by the correction above ---
    "does not provide",
    "doesn't provide",
    "do not have access to",
    "don't have access to",
    "cannot provide financial advice",
    "can't provide financial advice",
    "cannot provide legal advice",
    "can't provide legal advice",
    # --- second correction, from the red-team run ---
    # The red-team suite had its OWN copy of this list, which never received the
    # correction above and so re-made the same mistake: "does not provide
    # sufficient information" scored as an assertion. Both suites now share this
    # one list. Duplicated judgement logic drifts, and drifting judgement logic
    # produces metrics that disagree with each other for no visible reason.
    "does not appear",
    "no information",
    "not available in",
    "could not find",
    "does not mention",
    "no mention",
    "does not exist",
    "no such",
    "cannot confirm",
    "unable to confirm",
    "not supported by",
    "i don't have",
    "i do not have",
    "insufficient information",
    "not specify",
    "does not specify",
)


def is_refusal(answer: str) -> bool:
    """True when the answer declines instead of asserting a regulatory fact."""
    lowered = (answer or "").lower()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def score_citation_accuracy(
    cited: list[str], expected: list[str], known_doc_numbers: set[str] | None = None
) -> tuple[int, int]:
    """Return (correct_citations, total_citations) for one row.

    A citation counts as correct when it is a real document (present in the
    corpus, if a corpus is supplied) AND is one the row expected. Citing a real
    but irrelevant document is still wrong — "real" alone would let a system
    score well by citing any document it retrieved.
    """
    if not cited:
        return (0, 0)
    expected_set = set(expected)
    correct = 0
    for dn in cited:
        real = known_doc_numbers is None or dn in known_doc_numbers
        if real and dn in expected_set:
            correct += 1
    return (correct, len(cited))


def score_temporal_row(row: dict, cited: list[str], answer: str = "") -> bool | None:
    """Did this date-scoped row get answered without citing a wrong-era document?

    Returns None when the row isn't a scorable temporal case (so callers can
    exclude it from the denominator rather than counting it as a pass).
    """
    if row.get("difficulty") != "adversarial_temporal":
        return None
    forbidden = set(row.get("must_not_cite") or [])
    if not forbidden:
        return None          # asserts nothing; not scorable
    if set(cited) & forbidden:
        return False         # cited a document that wasn't in force — the failure
    expected = set(row.get("expected_doc_numbers") or [])
    if expected:
        return bool(expected & set(cited))
    # No retrievable in-force document for that date: citing nothing is correct,
    # and an explicit decline is what the response should say.
    return not cited


def score_refusal_row(row: dict, cited: list[str], answer: str) -> bool | None:
    """Was an out-of-scope question correctly declined?"""
    if row.get("difficulty") != "out_of_scope":
        return None
    # Correct = cited no regulation AND said so. Citing nothing while confidently
    # asserting an answer is still a failure.
    return (not cited) and is_refusal(answer)


@dataclass
class MetricResult:
    """A metric plus the denominator it was computed over.

    `value` is None when nothing was scorable. None means "not measured" and must
    stay distinct from 0.0 ("measured, and everything failed") all the way into
    the report and the eval_runs row — conflating them is how a broken harness
    starts looking like a broken system (docs/adr/0007).
    """

    name: str
    passed: int = 0
    total: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def value(self) -> float | None:
        return (self.passed / self.total) if self.total else None

    def add(self, ok: bool | None, label: str = "") -> None:
        if ok is None:
            return
        self.total += 1
        if ok:
            self.passed += 1
        elif label:
            self.failures.append(label)

    def render(self) -> str:
        if self.value is None:
            return f"{self.name}: n/a (0 scorable rows)"
        return f"{self.name}: {self.value:.1%} ({self.passed}/{self.total})"


def score_all(results: list[dict], known_doc_numbers: set[str] | None = None) -> dict:
    """Score a full eval run.

    `results` items: {"row": <golden row>, "cited": [...], "answer": str}
    """
    temporal = MetricResult("temporal_correctness")
    refusal = MetricResult("refusal_correctness")
    cite_correct = cite_total = 0

    for item in results:
        row, cited, answer = item["row"], item["cited"], item.get("answer", "")
        temporal.add(score_temporal_row(row, cited, answer), row["question"][:70])
        refusal.add(score_refusal_row(row, cited, answer), row["question"][:70])
        if row.get("expected_doc_numbers"):
            c, t = score_citation_accuracy(cited, row["expected_doc_numbers"], known_doc_numbers)
            cite_correct += c
            cite_total += t

    citation = MetricResult("citation_accuracy", passed=cite_correct, total=cite_total)
    return {
        "citation_accuracy": citation,
        "temporal_correctness": temporal,
        "refusal_correctness": refusal,
    }
