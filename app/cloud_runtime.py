"""Self-contained PageIndex runtime for Streamlit Community Cloud.

The production API keeps PostgreSQL as the source of truth.  This module reads a
small, generated snapshot of the reviewed pilot corpus so the public demo can run
on Streamlit's single-process hosting without Docker or a database service.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.agent.nodes.classify import classify_query
from app.agent.nodes.expand import expand_context
from app.agent.nodes.generate import generate_answer
from app.agent.nodes.groundedness import compute_groundedness
from app.agent.nodes.verify import verify_citations
from app.config import settings
from app.retrieval.pageindex_search import search


CORPUS_PATH = Path(__file__).resolve().parents[1] / "streamlit_data" / "corpus.json"
DISCLAIMER = "This is decision-support information, not legal advice."
_TOKENS = re.compile(r"[a-zA-Z0-9]+")
_NOISE = {
    "a", "an", "and", "are", "at", "bank", "by", "does", "for", "how", "in",
    "india", "is", "it", "may", "must", "nbfc", "nbfcs", "of", "or", "reserve",
    "rbi", "the", "to", "what", "when", "which", "with",
}


def _terms(text: str) -> list[str]:
    return [term for term in _TOKENS.findall(text.lower()) if term not in _NOISE and len(term) > 1]


def _as_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@lru_cache(maxsize=1)
def _payload() -> dict:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


class SnapshotRepository:
    """Repository interface used by pageindex_search.search."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.documents = {row["id"]: row for row in payload["documents"]}
        self.versions = {row["id"]: row for row in payload["versions"]}
        self.pages_by_version: dict[str, list[dict]] = {}
        self.nodes_by_version: dict[str, list[dict]] = {}
        for row in payload["pages"]:
            self.pages_by_version.setdefault(row["version_id"], []).append(row)
        for row in payload["nodes"]:
            self.nodes_by_version.setdefault(row["version_id"], []).append(row)

    def in_force(self, ref: date) -> set[str]:
        superseded_ids = {
            edge["predecessor_doc_id"]
            for edge in self.payload.get("supersession_edges", [])
            if edge["relation_type"] in {"supersedes", "consolidates"}
            and edge.get("extraction_method") in {"manual_verified", "rbi_explicit_list"}
            and _as_date(edge.get("effective_date"))
            and _as_date(edge["effective_date"]) <= ref
        }
        allowed = set()
        for doc in self.documents.values():
            issued = _as_date(doc["issue_date"])
            effective = _as_date(doc.get("effective_date")) or issued
            withdrawn = _as_date(doc.get("withdrawn_date"))
            if (
                issued <= ref
                and effective <= ref
                and doc["status"] != "draft"
                and (withdrawn is None or withdrawn > ref)
                and doc["id"] not in superseded_ids
            ):
                allowed.add(doc["doc_number"])
        return allowed

    def candidates(self, query: str, allowed: set[str], ref: date, limit: int) -> list[dict]:
        query_terms = Counter(_terms(query))
        ranked = []
        for version in self.versions.values():
            doc = self.documents[version["document_id"]]
            if doc["doc_number"] not in allowed:
                continue
            valid_from = _as_date(version["valid_from"])
            valid_to = _as_date(version.get("valid_to"))
            if valid_from > ref or (valid_to is not None and valid_to <= ref):
                continue
            page_text = " ".join(page["text"] for page in self.pages_by_version.get(version["id"], []))
            haystack = Counter(_terms(f"{doc['title']} {doc['doc_number']} {page_text}"))
            overlap = sum(min(count, haystack[term]) for term, count in query_terms.items())
            title_overlap = len(set(query_terms) & set(_terms(doc["title"])))
            score = overlap + title_overlap * 4
            if score:
                ranked.append(
                    {
                        "version_id": version["id"],
                        "doc_number": doc["doc_number"],
                        "title": doc["title"],
                        "source_url": doc["source_url"],
                        "content_hash": version["content_hash"],
                        "valid_from": version["valid_from"],
                        "valid_to": version.get("valid_to"),
                        "validity_basis": version["validity_basis"],
                        "index_kind": version["index_kind"],
                        "score": float(score),
                    }
                )
        ranked.sort(key=lambda item: (-item["score"], item["doc_number"]))
        return ranked[:limit]

    def nodes(self, version_id: str) -> list[dict]:
        return [dict(row) for row in self.nodes_by_version.get(version_id, [])]

    def pages(self, version_id: str, numbers: list[int]) -> list[dict]:
        wanted = set(numbers)
        return [
            dict(row)
            for row in self.pages_by_version.get(version_id, [])
            if row["page_number"] in wanted
        ]

    def lexical_pages(self, version_id: str, query: str, limit: int) -> list[dict]:
        query_terms = set(_terms(query))
        ranked = []
        for page in self.pages_by_version.get(version_id, []):
            overlap = len(query_terms & set(_terms(page["text"])))
            if overlap:
                ranked.append({**page, "rank": overlap})
        ranked.sort(key=lambda row: (-row["rank"], row["page_number"]))
        return ranked[:limit]

    def graph_neighbors(self, doc_numbers: list[str], allowed: set[str], ref: date) -> list[dict]:
        return self._relations(doc_numbers, allowed, ref, document_targets=True)

    def graph_evidence(
        self, query: str, doc_numbers: list[str], allowed: set[str], ref: date, limit: int
    ) -> list[dict]:
        query_terms = set(_terms(query))
        rows = self._relations(doc_numbers, allowed, ref, document_targets=False)
        ranked = []
        for row in rows:
            score = len(query_terms & set(_terms(f"{row['target']} {row['evidence_quote']}")))
            if score:
                ranked.append({**row, "score": score})
        ranked.sort(key=lambda row: (-row["score"], row["id"]))
        return ranked[:limit]

    def _relations(
        self, doc_numbers: list[str], allowed: set[str], ref: date, document_targets: bool
    ) -> list[dict]:
        rows = []
        for relation in self.payload.get("relations", []):
            valid_from = _as_date(relation["valid_from"])
            valid_to = _as_date(relation.get("valid_to"))
            target_is_doc = relation.get("target_kind") == "document"
            if (
                relation["source"] in doc_numbers
                and relation["source"] in allowed
                and target_is_doc == document_targets
                and (not target_is_doc or relation["target"] in allowed)
                and valid_from <= ref
                and (valid_to is None or valid_to > ref)
            ):
                rows.append(dict(relation))
        return rows


@lru_cache(maxsize=1)
def repository() -> SnapshotRepository:
    return SnapshotRepository(_payload())


def documents() -> list[dict]:
    return [dict(row) for row in _payload()["documents"]]


def run_cloud_query(
    question: str, reference_date: str | None = None, strategy: str = "pageindex"
) -> dict:
    """Run the safe retrieval/generation path against the bundled snapshot."""
    if strategy not in {"lexical", "pageindex", "graph_pageindex"}:
        raise ValueError("The hosted demo supports lexical and PageIndex retrieval only")
    classification = classify_query(question)
    ref_iso = reference_date or classification["reference_date"] or date.today().isoformat()
    ref = date.fromisoformat(ref_iso)
    if not classification["in_scope"]:
        return {
            "answer": "This question appears to be outside the scope of RBI/SEBI regulatory "
            f"compliance, so I won't answer it from the regulatory corpus.\n\n{DISCLAIMER}",
            "citations": [], "retrieved_sources": [], "reference_date_used": ref_iso,
            "in_force_docs": None, "model": None, "degraded": False,
            "verified_citations": True, "groundedness": None, "low_confidence": False,
            "retrieval_strategy": strategy, "graph_paths": [], "cached": False,
        }

    repo = repository()
    allowed = repo.in_force(ref)
    hits = search(question, 8, strategy, allowed, ref_iso, repository=repo)
    contexts = expand_context(hits)
    if not hits:
        answer, model, degraded = (
            "No applicable source text was found for this date. I cannot answer this question "
            f"from the available corpus.\n\n{DISCLAIMER}", None, False,
        )
    else:
        try:
            generated = generate_answer(question, contexts)
            answer, model, degraded = generated["answer"], generated["model"], False
        except Exception:
            answer, model, degraded = (
                "The answer service is unavailable. The relevant source passages are listed below.",
                None,
                True,
            )

    valid_docs, cited, hallucinated = verify_citations(answer, hits)
    evidence_cited = set(re.findall(r"\[(E:[^\]]+)\]", answer))
    evidence_known = {hit.get("citation_id") for hit in hits}
    hallucinated.extend(sorted(evidence_cited - evidence_known))
    if hits and not evidence_cited and not degraded:
        hallucinated.append("Missing page evidence citations")
    citations, seen = [], set()
    for hit in hits:
        citation_id = hit.get("citation_id")
        if citation_id in evidence_cited and citation_id not in seen:
            seen.add(citation_id)
            citations.append(
                {
                    "doc_number": hit["doc_number"], "title": hit["title"],
                    "url": hit["source_url"], "evidence_id": hit.get("evidence_id"),
                    "page_start": hit.get("page_start"), "page_end": hit.get("page_end"),
                    "evidence_url": None,
                }
            )
    verified = valid_docs and not hallucinated
    groundedness = None if degraded else compute_groundedness(answer, contexts)
    low_confidence = groundedness is not None and groundedness < settings.groundedness_threshold
    if not verified and not degraded:
        answer = f"I could not validate the generated citations. Please inspect the retrieved evidence directly.\n\n{DISCLAIMER}"
    elif low_confidence:
        answer = "⚠️ Low confidence — verify this answer against the cited documents:\n\n" + answer

    return {
        "answer": answer,
        "citations": citations,
        "retrieved_sources": [
            {
                "doc_number": hit["doc_number"], "title": hit["title"],
                "section_heading": hit.get("section_heading"), "score": round(hit["score"], 4),
                "evidence_id": hit.get("evidence_id"), "page_start": hit.get("page_start"),
                "page_end": hit.get("page_end"), "evidence_url": None, "text": hit.get("text"),
            }
            for hit in hits
        ],
        "reference_date_used": ref_iso, "in_force_docs": len(allowed), "model": model,
        "degraded": degraded, "verified_citations": verified,
        "hallucinated_citations": hallucinated, "groundedness": groundedness,
        "low_confidence": low_confidence, "retrieval_strategy": strategy,
        "corpus_revision": _payload()["corpus_revision"],
        "graph_paths": list({p["id"]: p for hit in hits for p in hit.get("graph_paths", [])}.values()),
        "cached": False,
    }
