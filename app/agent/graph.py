"""LangGraph agent wiring (spec §11).

Explicit state machine:

    classify ──in_scope?──> resolve_temporal ─> retrieve ─> generate
        │                                                      │
        └──out_of_scope──> refuse ─> END          verify ─> respond ─> END

Each node is a small function that reads AgentState and returns a partial update.
This makes the pipeline traceable and each node independently testable.
"""

from __future__ import annotations

import logging
from datetime import date

from langgraph.graph import END, START, StateGraph

from app.agent.cache import ExactCache
from app.agent.nodes.classify import classify_query
from app.agent.nodes.expand import expand_context
from app.agent.nodes.generate import generate_answer
from app.agent.nodes.groundedness import compute_groundedness
from app.agent.nodes.verify import verify_citations
from app.agent.state import AgentState
from app.config import settings
from app.db.queries import corpus_revision, get_connection
from app.observability.tracing import span
from app.prompts import GENERATION_PROMPT_VERSION
from app.retrieval.retrieve import retrieve
from app.retrieval.temporal_filter import in_force_doc_numbers
from app.retrieval.types import STRATEGIES, VECTOR_STRATEGIES

log = logging.getLogger(__name__)

DISCLAIMER = "This is decision-support information, not legal advice."


def _classify(state: AgentState) -> dict:
    with span("classify") as s:
        result = classify_query(state["question"])
        s.note(in_scope=result["in_scope"])
    # Explicit input date wins; otherwise use the date the classifier extracted.
    ref = state.get("reference_date") or result["reference_date"]
    return {"in_scope": result["in_scope"], "reference_date": ref}


def _resolve_temporal(state: AgentState) -> dict:
    with span("resolve_temporal") as s:
        ref = state.get("reference_date")
        ref_date = date.fromisoformat(ref) if ref else date.today()
        with get_connection() as conn:
            allowed = in_force_doc_numbers(conn, ref_date)
            revision = corpus_revision(conn, state["strategy"] not in VECTOR_STRATEGIES)
        s.note(reference_date=ref_date.isoformat(), in_force_docs=len(allowed))
    return {
        "ref_date_iso": ref_date.isoformat(),
        "allowed_doc_numbers": allowed,
        "corpus_revision": revision,
    }


def _retrieve(state: AgentState) -> dict:
    with span("retrieve", strategy=state["strategy"], k=8) as s:
        hits = retrieve(
            state["question"],
            k=8,
            strategy=state["strategy"],
            reference_date=state["ref_date_iso"],
            allowed_doc_numbers=state.get("allowed_doc_numbers"),
        )
        # Candidate doc numbers + scores are the single most useful thing to have
        # in a trace when a retrieval answer looks wrong.
        s.note(
            hits=len(hits),
            candidates=[{"doc": h["doc_number"], "score": round(h["score"], 4)} for h in hits],
        )
    return {"hits": hits}


def _expand(state: AgentState) -> dict:
    with span("expand") as s:
        contexts = expand_context(state["hits"])
        s.note(blocks=len(contexts))
    return {"contexts": contexts}


def _generate(state: AgentState) -> dict:
    if not state.get("hits"):
        return {
            "answer": "No applicable source text was found for this date. "
            "I cannot answer this question from the available corpus.\n\n" + DISCLAIMER,
            "model": None,
            "degraded": False,
        }
    with span("generate") as s:
        try:
            gen = generate_answer(state["question"], state.get("contexts") or state["hits"])
            s.note(model=gen["model"], degraded=False)
            return {"answer": gen["answer"], "model": gen["model"], "degraded": False}
        except Exception as exc:  # graceful degradation (spec §15)
            # The degraded answer text carries the reason too, but callers (e.g.
            # the eval harness) discard that text once they see degraded=True —
            # log here so the real cause isn't lost, only "degraded" is.
            log.warning("generate degraded: %s: %s", type(exc).__name__, exc)
            s.note(degraded=True, reason=type(exc).__name__)
            return {
                "answer": (
                    "The answer service is unavailable, so I can't generate a written answer. "
                    f"The relevant source passages are listed below. (reason: {type(exc).__name__})"
                ),
                "model": None,
                "degraded": True,
            }


def _verify(state: AgentState) -> dict:
    with span("verify") as s:
        ok, _cited, hallucinated = verify_citations(state["answer"], state["hits"])
        s.note(verified=ok, hallucinated=hallucinated)
    import re

    seen, citations = set(), []
    evidence_mode = any(h.get("evidence_id") for h in state["hits"])
    evidence_cited = set(re.findall(r"\[(E:[^\]]+)\]", state["answer"]))
    evidence_known = {h.get("citation_id") for h in state["hits"]}
    hallucinated.extend(sorted(evidence_cited - evidence_known))
    if evidence_mode and not evidence_cited:
        hallucinated.append("Missing page evidence citations")
    for h in state["hits"]:
        dn = h["doc_number"]
        key = h.get("evidence_id") or dn.lower()
        cited = (
            h.get("citation_id") in evidence_cited
            if evidence_mode
            else (dn.lower() in {c.lower() for c in _cited})
        )
        if cited and key not in seen:
            seen.add(key)
            citations.append(
                {
                    "doc_number": dn,
                    "title": h["title"],
                    "url": h["source_url"],
                    "evidence_id": h.get("evidence_id"),
                    "page_start": h.get("page_start"),
                    "page_end": h.get("page_end"),
                    "evidence_url": h.get("evidence_url"),
                }
            )
    return {
        "verified": ok and not hallucinated,
        "hallucinated": hallucinated,
        "citations": citations,
    }


def _groundedness(state: AgentState) -> dict:
    """Score answer support against context; flag low-confidence (spec §11.8)."""
    if state.get("degraded"):
        # A failed generation isn't "ungrounded" — don't score it (that would
        # report an outage as a quality problem).
        return {"groundedness": None, "low_confidence": False}
    contexts = state.get("contexts") or state.get("hits") or []
    score = compute_groundedness(state["answer"], contexts)
    return {
        "groundedness": score,
        "low_confidence": score < settings.groundedness_threshold,
    }


def _respond(state: AgentState) -> dict:
    allowed = state.get("allowed_doc_numbers")
    sources = [
        {
            "doc_number": h["doc_number"],
            "title": h["title"],
            "section_heading": h.get("section_heading"),
            "score": round(h["score"], 4),
            "evidence_id": h.get("evidence_id"),
            "page_start": h.get("page_start"),
            "page_end": h.get("page_end"),
            "evidence_url": h.get("evidence_url"),
            "text": h.get("text"),
        }
        for h in state.get("hits", [])
    ]
    answer = state["answer"]
    if not state.get("verified", True):
        answer = (
            "I could not validate the generated citations. "
            "Please inspect the retrieved evidence directly.\n\n" + DISCLAIMER
        )
    if state.get("low_confidence"):
        # Spec §11.8: below the groundedness threshold, say so rather than
        # presenting a weakly-supported answer as reliable.
        answer = (
            "⚠️ Low confidence — the retrieved sources only weakly support this "
            "answer, so treat it as a starting point and verify against the cited "
            f"documents:\n\n{answer}"
        )
    return {
        "response": {
            "answer": answer,
            "citations": state.get("citations", []),
            "retrieved_sources": sources,
            "reference_date_used": state.get("ref_date_iso", date.today().isoformat()),
            "in_force_docs": len(allowed) if allowed is not None else None,
            "model": state.get("model"),
            "degraded": state.get("degraded", False),
            "verified_citations": state.get("verified", True),
            "hallucinated_citations": state.get("hallucinated", []),
            "groundedness": state.get("groundedness"),
            "retrieval_strategy": state["strategy"],
            "corpus_revision": state.get("corpus_revision"),
            "graph_paths": list(
                {
                    p["id"]: p for h in state.get("hits", []) for p in h.get("graph_paths", [])
                }.values()
            ),
            "low_confidence": state.get("low_confidence", False),
        }
    }


def _refuse(state: AgentState) -> dict:
    return {
        "response": {
            "answer": (
                "This question appears to be outside the scope of RBI/SEBI regulatory "
                f"compliance, so I won't answer it from the regulatory corpus.\n\n{DISCLAIMER}"
            ),
            "citations": [],
            "retrieved_sources": [],
            "reference_date_used": state.get("reference_date") or date.today().isoformat(),
            "in_force_docs": None,
            "model": None,
            "degraded": False,
            "verified_citations": True,
            "hallucinated_citations": [],
            "groundedness": None,  # nothing retrieved to be grounded against
            "low_confidence": False,
        }
    }


def _route_scope(state: AgentState) -> str:
    return "resolve_temporal" if state.get("in_scope", True) else "refuse"


def build_agent():
    g = StateGraph(AgentState)
    g.add_node("classify", _classify)
    g.add_node("resolve_temporal", _resolve_temporal)
    g.add_node("cache_lookup", _cache_lookup)
    g.add_node("retrieve", _retrieve)
    g.add_node("expand", _expand)
    g.add_node("generate", _generate)
    g.add_node("verify", _verify)
    g.add_node("groundedness", _groundedness)
    g.add_node("respond", _respond)
    g.add_node("refuse", _refuse)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify",
        _route_scope,
        {"resolve_temporal": "resolve_temporal", "refuse": "refuse"},
    )
    g.add_edge("resolve_temporal", "cache_lookup")
    g.add_conditional_edges(
        "cache_lookup",
        lambda state: "hit" if state.get("response") else "miss",
        {"hit": END, "miss": "retrieve"},
    )
    g.add_edge("retrieve", "expand")
    g.add_edge("expand", "generate")
    g.add_edge("generate", "verify")
    g.add_edge("verify", "groundedness")
    g.add_edge("groundedness", "respond")
    g.add_edge("respond", END)
    g.add_edge("refuse", END)
    return g.compile()


_agent = None
_cache = ExactCache(ttl_seconds=settings.cache_ttl_seconds)


def _cache_lookup(state: AgentState) -> dict:
    key = (
        state["question"].strip(),
        state["ref_date_iso"],
        state["corpus_revision"],
        state["strategy"],
        settings.llm_provider,
        settings.llm_base_url,
        settings.llm_model,
        settings.llm_model_fast,
        settings.embedding_model,
        settings.groundedness_threshold,
        GENERATION_PROMPT_VERSION,
    )
    hit = _cache.get(key) if state.get("use_cache", True) else None
    return {"cache_key": key, **({"response": {**hit, "cached": True}} if hit else {})}


def run_agent(
    question: str,
    reference_date: str | None = None,
    use_cache: bool = True,
    strategy: str | None = None,
) -> dict:
    """Resolve date and corpus revision before consulting the exact cache."""
    global _agent
    strategy = strategy or settings.retrieval_strategy
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown retrieval strategy: {strategy}")
    if reference_date:
        reference_date = date.fromisoformat(reference_date).isoformat()
    if _agent is None:
        _agent = build_agent()
    final = _agent.invoke(
        {
            "question": question,
            "reference_date": reference_date,
            "strategy": strategy,
            "use_cache": use_cache,
        }
    )
    response = final["response"]
    response.setdefault("cached", False)
    if use_cache and final.get("cache_key") and not response.get("degraded"):
        if not response["cached"]:
            _cache.put(final["cache_key"], response)
    return response
