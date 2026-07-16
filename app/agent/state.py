"""Shared state for the LangGraph agent.

Each node receives this dict and returns a partial update. total=False means
every key is optional, so nodes only set what they compute.
"""

from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    # inputs
    question: str
    reference_date: str | None
    # classify
    in_scope: bool
    # resolve_temporal
    ref_date_iso: str
    allowed_doc_numbers: set[str]
    # retrieve / expand / generate
    hits: list[dict]
    contexts: list[dict]
    answer: str
    model: str | None
    degraded: bool
    # verify
    citations: list[dict]
    verified: bool
    hallucinated: list[str]
    # groundedness (spec §11.8)
    groundedness: float | None
    low_confidence: bool
    # respond
    response: dict
