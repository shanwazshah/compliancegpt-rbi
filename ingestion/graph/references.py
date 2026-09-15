"""Build verified, literal document cross-references from canonical source pages.

These edges mean REFERS_TO, never that one document legally supersedes another.
Only exact mentions of known document numbers are accepted; every edge keeps its quote.
"""

from __future__ import annotations

import re
import uuid

from app.db.queries import get_connection


def build_references(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT doc_number FROM documents ORDER BY doc_number")
        numbers = [row[0] for row in cur.fetchall()]
        entities = {
            number: str(uuid.uuid5(uuid.NAMESPACE_URL, f"document:{number}")) for number in numbers
        }
        for name, identity in entities.items():
            cur.execute(
                """INSERT INTO kg_entities(id,kind,canonical_name) VALUES (%s,'document',%s)
                   ON CONFLICT(kind,canonical_name) DO NOTHING""",
                (identity, name),
            )
        cur.execute(
            """SELECT v.id::text, d.doc_number, v.valid_from, v.valid_to,
                      p.page_number, p.text
               FROM evidence_pages p JOIN document_versions v ON v.id=p.version_id
               JOIN documents d ON d.id=v.document_id"""
        )
        pages = cur.fetchall()
        count = 0
        for version, source, start, end, number, text in pages:
            for target in numbers:
                if target == source:
                    continue
                match = re.search(
                    r"(?<![\w/])" + re.escape(target) + r"(?![\w/])", text, re.IGNORECASE
                )
                if not match:
                    continue
                quote = text[max(0, match.start() - 100) : match.end() + 100]
                identity = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, f"{version}:{number}:REFERS_TO:{target}")
                )
                cur.execute(
                    """INSERT INTO kg_relations
                       (id,subject_id,predicate,object_id,source_version_id,source_page,
                        evidence_quote,valid_from,valid_to,extraction_method,review_status)
                       VALUES (%s,%s,'REFERS_TO',%s,%s,%s,%s,%s,%s,'literal_reference','verified')
                       ON CONFLICT(id) DO NOTHING""",
                    (
                        identity,
                        entities[source],
                        entities[target],
                        version,
                        number,
                        quote,
                        start,
                        end,
                    ),
                )
                count += cur.rowcount
        if count:
            cur.execute("UPDATE evidence_revision SET revision=revision+1 WHERE singleton")
        return count


def main() -> None:
    with get_connection() as conn:
        count = build_references(conn)
    print(f"Added {count} source-backed cross-references")


if __name__ == "__main__":
    main()
