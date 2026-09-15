"""Postgres access for immutable page evidence and temporally scoped graph paths."""

from __future__ import annotations

import re
from datetime import date

from psycopg.rows import dict_row

_QUERY_NOISE = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "bank",
        "by",
        "does",
        "for",
        "how",
        "in",
        "india",
        "is",
        "it",
        "may",
        "must",
        "nbfc",
        "nbfcs",
        "of",
        "or",
        "reserve",
        "rbi",
        "the",
        "to",
        "what",
        "when",
        "which",
        "with",
    }
)


def _lexical_query(query: str) -> str:
    terms = [
        term
        for term in re.findall(r"[a-zA-Z0-9]+", query.lower())[:80]
        if term not in _QUERY_NOISE
    ]
    return " OR ".join(terms) or "regulation"

class EvidenceRepository:
    def __init__(self, conn):
        self.conn = conn

    def candidates(self, query: str, allowed: set[str], ref: date, limit: int) -> list[dict]:
        if not allowed:
            return []
        # Pick one applicable snapshot per document BEFORE relevance ranking.
        # A captured snapshot is eligible only from its explicit valid_from onward.
        lexical_query = _lexical_query(query)
        sql = """
            WITH query AS (
                SELECT websearch_to_tsquery('english', %s) AS terms
            ), versions AS (
                SELECT DISTINCT ON (v.document_id)
                       v.*, d.doc_number, d.title, d.source_url
                FROM document_versions v JOIN documents d ON d.id=v.document_id
                WHERE d.doc_number = ANY(%s)
                  AND v.valid_from <= %s AND (v.valid_to IS NULL OR v.valid_to > %s)
                ORDER BY v.document_id, v.valid_from DESC, v.captured_at DESC, v.id
            )
            SELECT v.id::text AS version_id, v.doc_number, v.title, v.source_url,
                   v.content_hash, v.valid_from, v.valid_to, v.validity_basis, v.index_kind,
                   COALESCE(MAX(ts_rank_cd(p.search_vector, q.terms)),0)
                   + 4 * ts_rank_cd(to_tsvector('english', v.title), q.terms)
                   + CASE WHEN position(lower(v.doc_number) in lower(%s)) > 0
                          THEN 10 ELSE 0 END AS score
            FROM versions v CROSS JOIN query q
            JOIN evidence_pages p ON p.version_id=v.id AND p.search_vector @@ q.terms
            GROUP BY v.id, v.doc_number, v.title, v.source_url, v.content_hash,
                     v.valid_from, v.valid_to, v.validity_basis, v.index_kind, q.terms
            ORDER BY score DESC, v.doc_number LIMIT %s
        """
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (lexical_query, sorted(allowed), ref, ref, query, limit))
            return cur.fetchall()
    def nodes(self, version_id: str) -> list[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT node_id, parent_id, title, summary, page_start, page_end
                   FROM document_nodes WHERE version_id=%s ORDER BY page_start, node_id""",
                (version_id,),
            )
            return cur.fetchall()

    def pages(self, version_id: str, numbers: list[int]) -> list[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT page_number, printed_label, text, text_hash FROM evidence_pages
                   WHERE version_id=%s AND page_number=ANY(%s) ORDER BY page_number""",
                (version_id, numbers),
            )
            return cur.fetchall()

    def lexical_pages(self, version_id: str, query: str, limit: int) -> list[dict]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """WITH query AS (SELECT websearch_to_tsquery('english', %s) AS terms)
                   SELECT page_number, printed_label, text, text_hash,
                          ts_rank_cd(search_vector, query.terms) AS rank
                   FROM evidence_pages CROSS JOIN query
                   WHERE version_id=%s AND search_vector @@ query.terms
                   ORDER BY rank DESC, page_number LIMIT %s""",
                (_lexical_query(query), version_id, limit),
            )
            return cur.fetchall()
    def graph_neighbors(self, doc_numbers: list[str], allowed: set[str], ref: date) -> list[dict]:
        if not doc_numbers or not allowed:
            return []
        with self.conn.cursor(row_factory=dict_row) as cur:
            # Verified one-hop references, with both relation AND source version validity.
            cur.execute(
                """SELECT r.id::text, s.canonical_name AS source,
                          o.canonical_name AS target, r.predicate, r.evidence_quote,
                          r.source_version_id::text, r.source_page
                   FROM kg_relations r JOIN kg_entities s ON s.id=r.subject_id
                   JOIN kg_entities o ON o.id=r.object_id
                   JOIN document_versions v ON v.id=r.source_version_id
                   JOIN documents d ON d.id=v.document_id
                   WHERE r.review_status='verified'
                     AND r.valid_from <= %s AND (r.valid_to IS NULL OR r.valid_to > %s)
                     AND v.valid_from <= %s AND (v.valid_to IS NULL OR v.valid_to > %s)
                     AND s.kind='document' AND o.kind='document'
                     AND s.canonical_name=ANY(%s) AND o.canonical_name=ANY(%s)
                     AND d.doc_number=s.canonical_name
                     AND NOT EXISTS (
                         SELECT 1 FROM document_versions newer
                         WHERE newer.document_id=v.document_id
                           AND newer.valid_from <= %s
                           AND (newer.valid_to IS NULL OR newer.valid_to > %s)
                           AND (newer.valid_from, newer.captured_at, newer.id)
                               > (v.valid_from, v.captured_at, v.id)
                     )
                   ORDER BY r.id LIMIT 50""",
                (ref, ref, ref, ref, doc_numbers, sorted(allowed), ref, ref),
            )
            return cur.fetchall()

    def graph_evidence(
        self, query: str, doc_numbers: list[str], allowed: set[str], ref: date, limit: int
    ) -> list[dict]:
        """Return reviewed concept relations whose quotes are relevant to the query.

        A relation is usable only while both it and its exact source snapshot are
        applicable. Candidate/rejected relations and stale source versions never
        reach retrieval.
        """
        if not doc_numbers or not allowed or limit < 1:
            return []
        lexical_query = _lexical_query(query)
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT r.id::text, s.canonical_name AS source,
                          o.canonical_name AS target, o.kind AS target_kind,
                          r.predicate, r.evidence_quote,
                          r.source_version_id::text, r.source_page,
                          ts_rank_cd(
                              to_tsvector('english', o.canonical_name || ' ' ||
                                  r.evidence_quote),
                              websearch_to_tsquery('english', %s)
                          ) AS score
                   FROM kg_relations r
                   JOIN kg_entities s ON s.id=r.subject_id
                   JOIN kg_entities o ON o.id=r.object_id
                   JOIN document_versions v ON v.id=r.source_version_id
                   JOIN documents d ON d.id=v.document_id
                   WHERE r.review_status='verified'
                     AND r.predicate IN ('REQUIRES','HAS_EXCEPTION','DEFINES','APPLIES_TO')
                     AND s.kind='document' AND o.kind <> 'document'
                     AND s.canonical_name=ANY(%s) AND s.canonical_name=ANY(%s)
                     AND d.doc_number=s.canonical_name
                     AND r.valid_from <= %s AND (r.valid_to IS NULL OR r.valid_to > %s)
                     AND v.valid_from <= %s AND (v.valid_to IS NULL OR v.valid_to > %s)
                     AND to_tsvector('english', o.canonical_name || ' ' ||
                             r.evidence_quote)
                         @@ websearch_to_tsquery('english', %s)
                     AND NOT EXISTS (
                         SELECT 1 FROM document_versions newer
                         WHERE newer.document_id=v.document_id
                           AND newer.valid_from <= %s
                           AND (newer.valid_to IS NULL OR newer.valid_to > %s)
                           AND (newer.valid_from, newer.captured_at, newer.id)
                               > (v.valid_from, v.captured_at, v.id)
                     )
                   ORDER BY score DESC, r.id LIMIT %s""",
                (
                    lexical_query,
                    doc_numbers,
                    sorted(allowed),
                    ref,
                    ref,
                    ref,
                    ref,
                    lexical_query,
                    ref,
                    ref,
                    limit,
                ),
            )
            return cur.fetchall()

    def revision(self) -> str:
        with self.conn.cursor() as cur:
            cur.execute("SELECT revision FROM evidence_revision WHERE singleton")
            return str(cur.fetchone()[0])

    def page_detail(self, version_id: str, page_number: int) -> dict | None:
        with self.conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """SELECT p.*, v.content_hash, v.valid_from, v.valid_to, v.validity_basis,
                          d.doc_number, d.title, d.source_url
                   FROM evidence_pages p JOIN document_versions v ON v.id=p.version_id
                   JOIN documents d ON d.id=v.document_id
                   WHERE p.version_id=%s AND p.page_number=%s""",
                (version_id, page_number),
            )
            return cur.fetchone()
