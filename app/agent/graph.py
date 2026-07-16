"""LangGraph agent wiring (spec §11).

Explicit state machine:

    classify ──in_scope?──> resolve_temporal ─> retrieve ─> generate
        │                                                      │
        └──out_of_scope──> refuse ─> END          verify ─> respond ─> END

Each node is a small function that reads AgentState and returns a partial update.
This makes the pipeline traceable and each node independently testable.
"""

from __future__ import annotations

from datetime import date

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.classify import classify_query
from app.agent.nodes.generate import generate_answer
from app.agent.nodes.verify import verify_citations
from app.agent.state import AgentState
from app.db.queries import get_connection
from app.retrieval.retrieve import retrieve
from app.retrieval.temporal_filter import in_force_doc_numbers

DISCLAIMER = "This is decision-support information, not legal advice."


def _classify(state: AgentState) -> dict:
    result = classify_query(state["question"])
    # Explicit input date wins; otherwise use the date the classifier extracted.
    ref = state.get("reference_date") or result["reference_date"]
    return {"in_scope": result["in_scope"], "reference_date": ref}


def _resolve_temporal(state: AgentState) -> dict:
    ref = state.get("reference_date")
    ref_date = date.fromisoformat(ref) if ref else date.today()
    with get_connection() as conn:
        allowed = in_force_doc_numbers(conn, ref_date)
    return {"ref_date_iso": ref_date.isoformat(), "allowed_doc_numbers": allowed}


def _retrieve(state: AgentState) -> dict:
    hits = retrieve(
        state["question"],
        k=8,
        strategy="dense",
        allowed_doc_numbers=state.get("allowed_doc_numbers"),
    )
    return {"hits": hits}


def _generate(state: AgentState) -> dict:
    try:
        gen = generate_answer(state["question"], state["hits"])
        return {"answer": gen["answer"], "model": gen["model"], "degraded": False}
    except Exception as exc:  # graceful degradation (spec §15)
        return {
            "answer": (
                "The answer service is unavailable, so I can't generate a written answer. "
                f"The relevant source passages are listed below. (reason: {type(exc).__name__})"
            ),
            "model": None,
            "degraded": True,
        }


def _verify(state: AgentState) -> dict:
    ok, _cited, hallucinated = verify_citations(state["answer"], state["hits"])
    seen, citations = set(), []
    for h in state["hits"]:
        dn = h["doc_number"]
        if dn in state["answer"] and dn not in seen:
            seen.add(dn)
            citations.append({"doc_number": dn, "title": h["title"], "url": h["source_url"]})
    return {"verified": ok, "hallucinated": hallucinated, "citations": citations}


def _respond(state: AgentState) -> dict:
    allowed = state.get("allowed_doc_numbers")
    sources = [
        {
            "doc_number": h["doc_number"],
            "title": h["title"],
            "section_heading": h.get("section_heading"),
            "score": round(h["score"], 4),
        }
        for h in state.get("hits", [])
    ]
    return {
        "response": {
            "answer": state["answer"],
            "citations": state.get("citations", []),
            "retrieved_sources": sources,
            "reference_date_used": state.get("ref_date_iso", date.today().isoformat()),
            "in_force_docs": len(allowed) if allowed is not None else None,
            "model": state.get("model"),
            "degraded": state.get("degraded", False),
            "verified_citations": state.get("verified", True),
            "hallucinated_citations": state.get("hallucinated", []),
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
            "reference_date_used": date.today().isoformat(),
            "in_force_docs": None,
            "model": None,
            "degraded": False,
            "verified_citations": True,
            "hallucinated_citations": [],
        }
    }


def _route_scope(state: AgentState) -> str:
    return "resolve_temporal" if state.get("in_scope", True) else "refuse"


def build_agent():
    g = StateGraph(AgentState)
    g.add_node("classify", _classify)
    g.add_node("resolve_temporal", _resolve_temporal)
    g.add_node("retrieve", _retrieve)
    g.add_node("generate", _generate)
    g.add_node("verify", _verify)
    g.add_node("respond", _respond)
    g.add_node("refuse", _refuse)

    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", _route_scope,
        {"resolve_temporal": "resolve_temporal", "refuse": "refuse"},
    )
    g.add_edge("resolve_temporal", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "verify")
    g.add_edge("verify", "respond")
    g.add_edge("respond", END)
    g.add_edge("refuse", END)
    return g.compile()


_agent = None
_cache = None


def run_agent(question: str, reference_date: str | None = None, use_cache: bool = True) -> dict:
    """Run the full agent and return the response payload (semantic-cached)."""
    global _agent, _cache
    if _agent is None:
        from app.agent.cache import SemanticCache

        _agent = build_agent()
        _cache = SemanticCache()

    if use_cache:
        hit = _cache.get(question, reference_date)
        if hit is not None:
            return {**hit, "cached": True}

    final = _agent.invoke({"question": question, "reference_date": reference_date})
    response = final["response"]
    response["cached"] = False
    if use_cache and not response.get("degraded"):
        _cache.put(question, reference_date, response)
    return response
