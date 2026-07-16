"""Phase 1 query pipeline: dense retrieve -> generate -> assemble response.

Deliberately a plain function, not a LangGraph agent yet. Phase 2 replaces this
with the full graph (classify -> resolve_temporal -> hybrid_retrieve -> rerank ->
expand -> generate -> verify_citations -> groundedness -> respond).
"""

from __future__ import annotations

from datetime import date

from app.agent.nodes.generate import generate_answer
from app.db.queries import get_connection
from app.retrieval.retrieve import retrieve
from app.retrieval.temporal_filter import in_force_doc_numbers


def answer_query(
    question: str,
    reference_date: str | None = None,
    k: int = 8,
    strategy: str = "dense",  # measured best on the golden set (see evals/ablation.py)
    temporal: bool = True,
) -> dict:
    """Answer one compliance question with citations and its retrieved sources.

    When `temporal` is on, retrieval is pre-filtered to the documents in force at
    `reference_date` (default = today), so the system never cites a document that
    was superseded (or not yet issued) as of that date.
    """
    ref_date = date.fromisoformat(reference_date) if reference_date else date.today()

    allowed: set[str] | None = None
    if temporal:
        with get_connection() as conn:
            allowed = in_force_doc_numbers(conn, ref_date)

    hits = retrieve(question, k=k, strategy=strategy, allowed_doc_numbers=allowed)
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
        "reference_date_used": ref_date.isoformat(),
        "in_force_docs": len(allowed) if allowed is not None else None,
        "model": model,
        "degraded": degraded,
    }
