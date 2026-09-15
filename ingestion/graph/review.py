"""Stage quoted graph proposals and record explicit local-operator reviews.

Quoted text proves provenance only, not the proposed relationship's correctness.
The caller owns the transaction. CLI reviews are trusted local operator actions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from app.db.queries import get_connection


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_version_id: UUID
    source_page: int = Field(ge=1)
    predicate: Literal["REQUIRES", "HAS_EXCEPTION", "DEFINES", "APPLIES_TO"]
    label: str = Field(min_length=1, max_length=2000)
    evidence_quote: str = Field(min_length=20, max_length=12000)


KINDS = {
    "REQUIRES": "obligation",
    "HAS_EXCEPTION": "exception",
    "DEFINES": "defined_term",
    "APPLIES_TO": "entity_class",
}


def list_relations(conn, status: str) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT r.id::text,r.predicate,o.canonical_name,r.source_version_id::text,
            r.source_page,r.evidence_quote,d.doc_number,d.title,d.source_url,
            v.valid_from,v.valid_to,p.text
            FROM kg_relations r
            JOIN kg_entities o ON o.id=r.object_id
            JOIN document_versions v ON v.id=r.source_version_id
            JOIN documents d ON d.id=v.document_id
            JOIN evidence_pages p ON p.version_id=r.source_version_id
                AND p.page_number=r.source_page
            WHERE r.review_status=%s ORDER BY d.doc_number,r.source_page,r.id""",
            (status,),
        )
        columns = [column.name for column in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def render_review_packet(relations: list[dict], status: str) -> str:
    lines = [
        f"# Knowledge-graph review packet: {status}",
        "",
        f"Relations: {len(relations)}",
        "",
        "A matching quote proves provenance only. Review the full page, current validity,",
        "predicate, label, applicability and exceptions before changing a relation's status.",
    ]
    for index, relation in enumerate(relations, 1):
        label = relation["canonical_name"].split(" :: ", 1)[-1]
        valid_to = relation["valid_to"] or "open"
        lines.extend(
            [
                "",
                f"## {index}. {label}",
                "",
                f"- Relation ID: `{relation['id']}`",
                f"- Predicate: `{relation['predicate']}`",
                f"- Document: `{relation['doc_number']}` — {relation['title']}",
                f"- Physical page: {relation['source_page']}",
                f"- Evidence version: `{relation['source_version_id']}`",
                f"- Validity: {relation['valid_from']} to {valid_to}",
                f"- Source: {relation['source_url']}",
                "",
                "### Proposed evidence quote",
                "",
                "```text",
                relation["evidence_quote"],
                "```",
                "",
                "### Full canonical physical page",
                "",
                "```text",
                relation["text"],
                "```",
            ]
        )
    return "\n".join(lines) + "\n"

def entity(cur, kind, name):
    identity = uuid5(NAMESPACE_URL, f"{kind}:{name}")
    cur.execute(
        """INSERT INTO kg_entities(id,kind,canonical_name) VALUES (%s,%s,%s)
                ON CONFLICT(kind,canonical_name)
                DO UPDATE SET canonical_name=EXCLUDED.canonical_name
                RETURNING id""",
        (identity, kind, name),
    )
    return cur.fetchone()[0]


def stage(conn, proposal: Proposal) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT d.doc_number,p.text,v.valid_from,v.valid_to
            FROM evidence_pages p JOIN document_versions v ON v.id=p.version_id
            JOIN documents d ON d.id=v.document_id WHERE p.version_id=%s AND p.page_number=%s""",
            (proposal.source_version_id, proposal.source_page),
        )
        source = cur.fetchone()
        if not source or proposal.evidence_quote not in source[1]:
            raise ValueError("Proposal quote must occur exactly on the cited canonical page")
        subject = entity(cur, "document", source[0])
        # Scope extracted concepts to this document; avoid merging legal meanings by label.
        obj = entity(cur, KINDS[proposal.predicate], source[0] + " :: " + proposal.label)
        identity = uuid5(NAMESPACE_URL, "proposal:" + proposal.model_dump_json())
        cur.execute(
            """INSERT INTO kg_relations(id,subject_id,predicate,object_id,
            source_version_id,source_page,evidence_quote,valid_from,valid_to,
            extraction_method,review_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,
            'quoted_proposal_v1','candidate') ON CONFLICT(id) DO NOTHING""",
            (
                identity,
                subject,
                proposal.predicate,
                obj,
                proposal.source_version_id,
                proposal.source_page,
                proposal.evidence_quote,
                source[2],
                source[3],
            ),
        )
    return str(identity)


def review(conn, relation_id: UUID, expected: str, status: str, reviewer: str, reason: str):
    if (
        status not in {"candidate", "verified", "rejected"}
        or not reviewer.strip()
        or not reason.strip()
    ):
        raise ValueError("Review requires a valid status, reviewer and reason")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT r.review_status,r.evidence_quote,p.text FROM kg_relations r
            JOIN evidence_pages p ON p.version_id=r.source_version_id
            AND p.page_number=r.source_page
            WHERE r.id=%s FOR UPDATE OF r""",
            (relation_id,),
        )
        row = cur.fetchone()
        if not row or row[0] != expected:
            raise ValueError("Relation missing or review state changed; reload before reviewing")
        if status == row[0]:
            raise ValueError("Review must change the current state")
        if status == "verified" and row[1] not in row[2]:
            raise ValueError("Cannot verify a relation whose source quote no longer matches")
        cur.execute("UPDATE kg_relations SET review_status=%s WHERE id=%s", (status, relation_id))
        cur.execute(
            """INSERT INTO kg_relation_reviews
            (relation_id,previous_status,new_status,reviewer,reason) VALUES (%s,%s,%s,%s,%s)""",
            (relation_id, row[0], status, reviewer.strip(), reason.strip()),
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("stage")
    ingest.add_argument("file", type=Path, help="JSON list of source-quoted proposals")
    inspect = commands.add_parser("list")
    inspect.add_argument(
        "--status", choices=["candidate", "verified", "rejected"], default="candidate"
    )
    change = commands.add_parser("review")
    change.add_argument("relation_id", type=UUID)
    change.add_argument("--expected", choices=["candidate", "verified", "rejected"], required=True)
    change.add_argument("--status", choices=["candidate", "verified", "rejected"], required=True)
    change.add_argument("--reviewer", required=True)
    change.add_argument("--reason", required=True)
    export = commands.add_parser("export")
    export.add_argument("output", type=Path)
    export.add_argument(
        "--status", choices=["candidate", "verified", "rejected"], default="candidate"
    )
    args = parser.parse_args()
    with get_connection() as conn:
        if args.command == "stage":
            proposals = [
                Proposal.model_validate(x)
                for x in json.loads(args.file.read_text(encoding="utf-8"))
            ]
            print(json.dumps([stage(conn, p) for p in proposals]))
        elif args.command == "review":
            review(conn, args.relation_id, args.expected, args.status, args.reviewer, args.reason)
            print("Review recorded")
        elif args.command == "list":
            print(json.dumps(list_relations(conn, args.status), default=str))
        else:
            relations = list_relations(conn, args.status)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render_review_packet(relations, args.status), encoding="utf-8")
            print(f"Wrote {len(relations)} relations to {args.output}")


if __name__ == "__main__":
    main()
