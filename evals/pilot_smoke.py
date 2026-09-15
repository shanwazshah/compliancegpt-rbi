"""Run one explicit live API smoke check; this is not a quality benchmark."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--strategy", choices=["lexical", "pageindex", "graph_pageindex"], default="pageindex"
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
    with TestClient(app) as client:
        response = client.post(
            "/api/query",
            headers=headers,
            json={
                "question": args.question,
                "reference_date": args.date,
                "strategy": args.strategy,
            },
        )
        payload = response.json()
        evidence_status = {}
        for citation in payload.get("citations", []):
            url = citation.get("evidence_url")
            if url:
                evidence_status[url] = client.get(url, headers=headers).status_code
    report = {
        "checked_at": datetime.now(UTC).isoformat(),
        "question": args.question,
        "strategy": args.strategy,
        "status_code": response.status_code,
        "response": payload,
        "citation_endpoint_status": evidence_status,
        "scope": "Single live smoke check, not claim-support or completeness evaluation",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "status_code": response.status_code,
                "degraded": payload.get("degraded"),
                "verified_citations": payload.get("verified_citations"),
                "citation_count": len(payload.get("citations", [])),
                "source_count": len(payload.get("retrieved_sources", [])),
                "evidence_endpoints_ok": bool(evidence_status)
                and all(s == 200 for s in evidence_status.values()),
                "report": str(args.output),
            }
        )
    )
    if (
        response.status_code != 200
        or payload.get("degraded")
        or not payload.get("verified_citations")
        or not evidence_status
        or not all(status == 200 for status in evidence_status.values())
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
