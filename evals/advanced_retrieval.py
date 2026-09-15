"""Evaluate lexical and PageIndex retrieval against checked physical-page locations.

The dataset confirms where the relevant source text appears. It has not received
legal-answer review, so this runner measures retrieval and evidence integrity only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean, median

from app.config import settings
from app.db.queries import get_connection
from app.evidence.repository import EvidenceRepository
from app.retrieval.retrieve import retrieve

DEFAULT_DATASET = Path("evals/advanced_pilot.jsonl")
STRATEGIES = ("lexical", "pageindex", "graph_pageindex")


def load_dataset(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc.msg}") from exc
        required = {
            "id",
            "question",
            "reference_date",
            "expected_doc_number",
            "expected_pages",
            "review_status",
        }
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(f"{path}:{line_number}: missing {', '.join(missing)}")
        if row["review_status"] != "source_location_checked":
            raise ValueError(f"{path}:{line_number}: source location is not checked")
        date.fromisoformat(row["reference_date"])
        if not isinstance(row["expected_pages"], list) or not row["expected_pages"]:
            raise ValueError(f"{path}:{line_number}: expected_pages must be a non-empty list")
        if any(type(page) is not int or page < 1 for page in row["expected_pages"]):
            raise ValueError(f"{path}:{line_number}: expected_pages must contain positive integers")
        string_fields = required - {"expected_pages"}
        if not all(isinstance(row[field], str) and row[field].strip() for field in string_fields):
            raise ValueError(f"{path}:{line_number}: required strings cannot be empty")
        rows.append(row)
    if not rows:
        raise ValueError(f"{path}: dataset is empty")
    ids = [row["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate row IDs")
    return rows


def _rank(hits: list[dict], predicate: Callable[[dict], bool]) -> int | None:
    return next((rank for rank, hit in enumerate(hits, 1) if predicate(hit)), None)


def score_case(
    row: dict,
    hits: list[dict],
    evidence_resolves: Callable[[dict], bool],
) -> dict:
    expected_doc = row["expected_doc_number"]
    expected_pages = set(row["expected_pages"])
    document_rank = _rank(hits, lambda hit: hit.get("doc_number") == expected_doc)
    page_rank = _rank(
        hits,
        lambda hit: hit.get("doc_number") == expected_doc
        and any(
            int(hit.get("page_start", 0)) <= page <= int(hit.get("page_end", 0))
            for page in expected_pages
        ),
    )
    resolved = [bool(evidence_resolves(hit)) for hit in hits]
    return {
        "document_rank": document_rank,
        "page_rank": page_rank,
        "document_hit": document_rank is not None,
        "page_hit": page_rank is not None,
        "retrieved": [
            {
                "doc_number": hit.get("doc_number"),
                "page_start": hit.get("page_start"),
                "page_end": hit.get("page_end"),
                "evidence_id": hit.get("evidence_id"),
                "evidence_resolved": resolved[index],
            }
            for index, hit in enumerate(hits)
        ],
        "resolved_evidence": sum(resolved),
        "returned_evidence": len(resolved),
    }


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def evaluate(
    rows: list[dict],
    strategy: str,
    k: int,
    retriever: Callable[..., list[dict]],
    evidence_resolves: Callable[[dict], bool],
) -> dict:
    results = []
    latencies = []
    for row in rows:
        started = time.perf_counter()
        try:
            hits = retriever(
                row["question"],
                k=k,
                strategy=strategy,
                reference_date=row["reference_date"],
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            result = score_case(row, hits, evidence_resolves)
            result.update(
                {
                    "id": row["id"],
                    "question": row["question"],
                    "expected_doc_number": row["expected_doc_number"],
                    "expected_pages": row["expected_pages"],
                    "latency_ms": latency_ms,
                    "error": None,
                }
            )
        except Exception as exc:
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            result = {
                "id": row["id"],
                "question": row["question"],
                "expected_doc_number": row["expected_doc_number"],
                "expected_pages": row["expected_pages"],
                "document_rank": None,
                "page_rank": None,
                "document_hit": False,
                "page_hit": False,
                "retrieved": [],
                "resolved_evidence": 0,
                "returned_evidence": 0,
                "latency_ms": latency_ms,
                "error": f"{type(exc).__name__}: {exc}",
            }
        latencies.append(latency_ms)
        results.append(result)

    count = len(results)
    document_hits = sum(item["document_hit"] for item in results)
    page_hits = sum(item["page_hit"] for item in results)
    resolved = sum(item["resolved_evidence"] for item in results)
    returned = sum(item["returned_evidence"] for item in results)
    errors = sum(item["error"] is not None for item in results)
    return {
        "metrics": {
            "document_recall_at_k": {
                "value": document_hits / count,
                "passed": document_hits,
                "total": count,
            },
            "physical_page_recall_at_k": {
                "value": page_hits / count,
                "passed": page_hits,
                "total": count,
            },
            "evidence_resolution_rate": {
                "value": (resolved / returned) if returned else None,
                "passed": resolved,
                "total": returned,
            },
            "retrieval_errors": errors,
            "latency_ms": {
                "mean": round(mean(latencies), 2),
                "p50": round(median(latencies), 2),
                "p95": round(_percentile(latencies, 0.95), 2),
            },
        },
        "results": results,
    }


def _real_evidence_resolver(repository: EvidenceRepository, hit: dict) -> bool:
    version_id = hit.get("version_id")
    page_number = hit.get("page_start")
    evidence_id = hit.get("evidence_id")
    if not version_id or type(page_number) is not int:
        return False
    if evidence_id != f"{version_id}:{page_number}":
        return False
    detail = repository.page_detail(version_id, page_number)
    return bool(detail and detail["doc_number"] == hit.get("doc_number"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--strategy", choices=STRATEGIES, default="lexical")
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be positive")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    dataset_bytes = args.dataset.read_bytes()
    rows = load_dataset(args.dataset)
    if args.limit is not None:
        rows = rows[: args.limit]
    with get_connection() as conn:
        repository = EvidenceRepository(conn)
        evaluated = evaluate(
            rows,
            args.strategy,
            args.k,
            retrieve,
            lambda hit: _real_evidence_resolver(repository, hit),
        )
        revision = repository.revision()

    report = {
        "schema_version": 1,
        "checked_at": datetime.now(UTC).isoformat(),
        "scope": (
            "Retrieval and immutable-evidence integrity only. Source locations were "
            "checked; legal answer correctness and completeness were not reviewed."
        ),
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "dataset_rows": len(rows),
        "strategy": args.strategy,
        "k": args.k,
        "corpus_revision": revision,
        "retrieval_settings": {
            "max_documents": settings.retrieval_max_documents,
            "navigation_documents": settings.retrieval_navigation_documents,
            "max_pages": settings.retrieval_max_pages,
            "max_rounds": settings.retrieval_max_rounds,
            "max_context_chars": settings.retrieval_max_context_chars,
            "navigation_mode": settings.pageindex_navigation_mode,
            "llm_timeout_seconds": settings.llm_timeout_seconds,
            "llm_max_retries": settings.llm_max_retries,
            "navigator_model": (
                settings.llm_model_fast
                if args.strategy != "lexical"
                and settings.pageindex_navigation_mode == "llm"
                else None
            ),
        },
        **evaluated,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    metrics = report["metrics"]
    print(
        json.dumps(
            {
                "strategy": args.strategy,
                "rows": len(rows),
                "document_recall_at_k": metrics["document_recall_at_k"]["value"],
                "physical_page_recall_at_k": metrics["physical_page_recall_at_k"]["value"],
                "evidence_resolution_rate": metrics["evidence_resolution_rate"]["value"],
                "retrieval_errors": metrics["retrieval_errors"],
                "latency_p95_ms": metrics["latency_ms"]["p95"],
                "report": str(args.output),
            }
        )
    )
    if metrics["retrieval_errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
