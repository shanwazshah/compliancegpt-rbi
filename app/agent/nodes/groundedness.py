"""Groundedness node (spec §11.8).

Scores how well the generated answer is supported by the retrieved context, and
lets the agent refuse rather than guess when confidence is low.

Two-tier design, deliberately:
  1. A cheap LEXICAL check (no LLM call): what fraction of the answer's
     content-bearing terms actually appear in the retrieved context? This never
     rate-limits and always produces a number.
  2. An optional LLM judge for a semantic score.

Tier 1 is the default because an LLM judge that fails (rate limit, outage) would
otherwise silently score 0 and make the system refuse valid answers — the same
class of silent-failure bug caught in the eval harness.

Below settings.groundedness_threshold the agent returns a low-confidence
response instead of presenting the answer as reliable.
"""

from __future__ import annotations

import re

# Words too common to signal grounding; ignored when scoring overlap.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "at", "by",
    "is", "are", "was", "were", "be", "been", "as", "that", "this", "it", "its",
    "with", "from", "shall", "may", "any", "all", "not", "no", "if", "which",
    "such", "there", "these", "those", "have", "has", "had", "will", "would",
    "can", "could", "should", "must", "information", "decision", "support",
    "legal", "advice", "according", "provided", "context", "answer", "question",
}


def _terms(text: str) -> set[str]:
    """Content-bearing tokens: words >2 chars plus any doc-number-ish tokens."""
    words = re.findall(r"[a-z0-9][a-z0-9./-]{2,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def lexical_groundedness(answer: str, contexts: list[dict]) -> float:
    """Fraction of the answer's content terms that appear in the context (0..1).

    1.0 = every term is traceable to retrieved text; low = the model introduced
    terms that aren't in the sources (a hallucination signal).
    """
    answer_terms = _terms(answer)
    if not answer_terms:
        return 0.0
    context_terms: set[str] = set()
    for c in contexts:
        context_terms |= _terms(c.get("text", ""))
    if not context_terms:
        return 0.0
    supported = answer_terms & context_terms
    return len(supported) / len(answer_terms)


def compute_groundedness(answer: str, contexts: list[dict]) -> float:
    """Return a 0..1 groundedness score for the answer given its context."""
    return round(lexical_groundedness(answer, contexts), 3)
