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
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "for",
    "on",
    "at",
    "by",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "as",
    "that",
    "this",
    "it",
    "its",
    "with",
    "from",
    "shall",
    "may",
    "any",
    "all",
    "if",
    "which",
    "such",
    "there",
    "these",
    "those",
    "have",
    "has",
    "had",
    "will",
    "would",
    "can",
    "could",
    "should",
    "must",
    "information",
    "decision",
    "support",
    "legal",
    "advice",
    "according",
    "provided",
    "context",
    "answer",
    "question",
}


def _terms(text: str) -> set[str]:
    """Content-bearing tokens: words >2 chars plus any doc-number-ish tokens."""
    words = re.findall(r"[a-z][a-z./-]{2,}|[0-9]+(?:[.,][0-9]+)*", text.lower())
    return {w for w in words if w not in _STOPWORDS}


_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "twelve": "12",
}
_QUANTITY_RE = re.compile(
    r"\b(?P<value>\d+(?:[.,]\d+)?|" + "|".join(_NUMBER_WORDS) + r")\s*"
    r"(?P<unit>%|percent|years?|months?|days?|crores?|lakhs?|basis points?)\b",
    re.I,
)
_RISK_RE = re.compile(r"\b(high|medium|low)(?:[- ]risk)?\b", re.I)
_NEGATION_RE = re.compile(r"\b(no|not|never|neither|nor|without|prohibited|forbidden)\b", re.I)


def _quantity_mentions(text: str) -> list[tuple[str, str, str | None]]:
    mentions = []
    for match in _QUANTITY_RE.finditer(text):
        value = _NUMBER_WORDS.get(match["value"].lower(), match["value"].replace(",", ""))
        unit = match["unit"].lower().rstrip("s")
        if unit == "%":
            unit = "percent"
        nearby = []
        for risk in _RISK_RE.finditer(text[max(0, match.start() - 80) : match.end() + 80]):
            absolute = max(0, match.start() - 80) + risk.start()
            nearby.append((abs(absolute - match.start()), risk.group(1).lower()))
        qualifier = min(nearby)[1] if nearby else None
        mentions.append((value, unit, qualifier))
    return mentions


def _unsupported_local_claim(answer: str, source: str) -> bool:
    """Catch quantity/qualifier swaps and unsupported negative assertions.

    This is deliberately conservative and deterministic. It is an error detector,
    not a claim that lexical matching proves legal entailment.
    """
    source_quantities = _quantity_mentions(source)
    for value, unit, qualifier in _quantity_mentions(answer):
        matches = [item for item in source_quantities if item[:2] == (value, unit)]
        if not matches or (qualifier and not any(item[2] == qualifier for item in matches)):
            return True
    source_clauses = re.split(r"[.!?;\n]+", source)
    for clause in re.split(r"[.!?;\n]+", answer):
        if not _NEGATION_RE.search(clause):
            continue
        terms = _terms(clause)
        supported = any(
            _NEGATION_RE.search(candidate) and len(terms & _terms(candidate)) >= min(2, len(terms))
            for candidate in source_clauses
        )
        if not supported:
            return True
    return False


def lexical_groundedness(answer: str, contexts: list[dict]) -> float:
    """Fraction of the answer's content terms that appear in the context (0..1).

    1.0 = every term is traceable to retrieved text; low = the model introduced
    terms that aren't in the sources (a hallucination signal).
    """
    # Citations are identifiers, not factual numeric claims.
    answer = re.sub(r"\[(?:RBI|SEBI|E:)[^\]]*\]", "", answer, flags=re.I)
    answer_terms = _terms(answer)
    if not answer_terms:
        return 0.0
    context_terms: set[str] = set()
    for c in contexts:
        context_terms |= _terms(c.get("text", ""))
    if not context_terms:
        return 0.0
    source = " ".join(c.get("text", "") for c in contexts)
    if _unsupported_local_claim(answer, source):
        return 0.0
    supported = answer_terms & context_terms
    return len(supported) / len(answer_terms)


def compute_groundedness(answer: str, contexts: list[dict]) -> float:
    """Return a 0..1 groundedness score for the answer given its context."""
    return round(lexical_groundedness(answer, contexts), 3)
