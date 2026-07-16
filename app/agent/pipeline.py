"""Phase 1 query pipeline: dense retrieve -> generate -> assemble response.

Deliberately a plain function, not a LangGraph agent yet. Phase 2 replaces this
with the full graph (classify -> resolve_temporal -> hybrid_retrieve -> rerank ->
expand -> generate -> verify_citations -> groundedness -> respond).
"""

from __future__ import annotations

from datetime import date

from app.agent.nodes.generate import generate_answer
from app.retrieval.retrieve import retrieve


def answer_query(
    question: str,
    reference_date: str | None = None,
    k: int = 8,
    strategy: str = "dense",  # measured best on the golden set (see evals/ablation.py)
) -> dict:
    """Answer one compliance question with citations and its retrieved sources."""
    hits = retrieve(question, k=k, strategy=strategy)
    retrieved_sources = [
        {
            "doc_number": h["doc_number"],
            "title": h["title"],
            "section_heading": h.get("section_heading"),
            "score": round(h["score"], 4),
        }
        for h in hits
    ]

    try:
        gen = generate_answer(question, hits)
        answer = gen["answer"]
        model = gen["model"]
        degraded = False
    except Exception as exc:  # graceful degradation (spec §15): serve passages, no generation
        answer = (
            "The answer service is unavailable, so I can't generate a written answer. "
            "The most relevant source passages are listed below. "
            f"(reason: {type(exc).__name__})"
        )
        model = None
        degraded = True

    # Citations = retrieved documents whose number actually appears in the answer.
    citations, seen = [], set()
    for h in hits:
        dn = h["doc_number"]
        if dn in answer and dn not in seen:
            seen.add(dn)
            citations.append({"doc_number": dn, "title": h["title"], "url": h["source_url"]})

    return {
        "answer": answer,
        "citations": citations,
        "retrieved_sources": retrieved_sources,
        "reference_date_used": reference_date or date.today().isoformat(),
        "model": model,
        "degraded": degraded,
    }
