"""Real Postgres contracts. CI applies migrations and runs these without mocks."""

from datetime import date
from uuid import uuid4

import psycopg
import pytest

from app.config import settings
from app.evidence.repository import EvidenceRepository
from app.retrieval.temporal_filter import in_force_doc_numbers

pytestmark = pytest.mark.integration


@pytest.fixture
def conn():
    connection = psycopg.connect(settings.database_url, connect_timeout=3)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def seed(conn, name, start="2024-01-01"):
    doc, version = str(uuid4()), str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO documents(id,source_regulator,doc_type,doc_number,title,
                       issue_date,source_url) VALUES (%s,'RBI','circular',%s,%s,%s,%s)""",
            (doc, name, "Synthetic KYC requirements", start, "https://example.org/test"),
        )
        cur.execute(
            """INSERT INTO document_versions
                       (id,document_id,content_hash,pdf_path,valid_from,validity_basis,
                        parser_version,index_kind)
                       VALUES (%s,%s,'test-hash','test.pdf',%s,'verified','test','pageindex')""",
            (version, doc, start),
        )
        cur.execute(
            """INSERT INTO evidence_pages(version_id,page_number,text,text_hash)
                       VALUES (%s,1,'The minimum ratio is 15 percent.','test-text-hash')""",
            (version,),
        )
    return doc, version


def test_candidates_use_applicable_snapshot_before_ranking(conn):
    name = "TEST/ADV/" + str(uuid4())
    doc, old = seed(conn, name)
    newer = str(uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO document_versions
            (id,document_id,content_hash,pdf_path,valid_from,validity_basis,parser_version)
            VALUES (%s,%s,'new','new.pdf','2025-01-01','verified','test')""",
            (newer, doc),
        )
        cur.execute(
            """INSERT INTO evidence_pages(version_id,page_number,text,text_hash)
            VALUES (%s,1,'The minimum ratio is 20 percent.','new-text')""",
            (newer,),
        )
    repo = EvidenceRepository(conn)
    assert repo.candidates("minimum ratio", {name}, date(2024, 6, 1), 5)[0]["version_id"] == old
    assert repo.candidates("minimum ratio", {name}, date(2025, 6, 1), 5)[0]["version_id"] == newer
    assert repo.candidates("minimum ratio", set(), date(2025, 6, 1), 5) == []
    assert repo.pages(old, [1])[0]["text"].endswith("15 percent.")

def test_candidate_ranking_ignores_corpus_wide_regulatory_terms(conn):
    relevant = "TEST/RANK/" + str(uuid4())
    distractor = "TEST/RANK/" + str(uuid4())
    _, relevant_version = seed(conn, relevant)
    _, distractor_version = seed(conn, distractor)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE evidence_pages SET text=%s WHERE version_id=%s",
            ("Anonymous, fictitious and benami account names are prohibited.", relevant_version),
        )
        cur.execute(
            "UPDATE evidence_pages SET text=%s WHERE version_id=%s",
            ("An NBFC branch may open an account.", distractor_version),
        )
    repo = EvidenceRepository(conn)
    ranked = repo.candidates(
        "May an NBFC open an anonymous, fictitious or benami account?",
        {relevant, distractor},
        date(2026, 1, 1),
        2,
    )
    assert [item["doc_number"] for item in ranked] == [relevant, distractor]


def test_amendment_does_not_retire_whole_predecessor(conn):
    old_name, new_name = "TEST/ADV/" + str(uuid4()), "TEST/ADV/" + str(uuid4())
    old, _ = seed(conn, old_name)
    new, _ = seed(conn, new_name)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO supersession_edges
            (predecessor_doc_id,successor_doc_id,relation_type,effective_date,extraction_method)
            VALUES (%s,%s,'amends','2024-05-01','manual_verified')""",
            (old, new),
        )
    assert old_name in in_force_doc_numbers(conn, date(2024, 6, 1))


def test_drafts_and_future_commencement_are_excluded(conn):
    name = "TEST/ADV/" + str(uuid4())
    doc, _ = seed(conn, name)
    with conn.cursor() as cur:
        cur.execute("UPDATE documents SET effective_date='2025-01-01' WHERE id=%s", (doc,))
    assert name not in in_force_doc_numbers(conn, date(2024, 6, 1))
    with conn.cursor() as cur:
        cur.execute("UPDATE documents SET status='draft' WHERE id=%s", (doc,))
    assert name not in in_force_doc_numbers(conn, date(2025, 6, 1))


def test_graph_filters_review_state_and_source_validity(conn):
    source, target = "TEST/ADV/" + str(uuid4()), "TEST/ADV/" + str(uuid4())
    _, version = seed(conn, source, "2025-01-01")
    seed(conn, target, "2024-01-01")
    subject, obj, relation = str(uuid4()), str(uuid4()), str(uuid4())
    with conn.cursor() as cur:
        for identity, name in [(subject, source), (obj, target)]:
            cur.execute("INSERT INTO kg_entities VALUES (%s,'document',%s,'{}')", (identity, name))
        cur.execute(
            """INSERT INTO kg_relations
            (id,subject_id,predicate,object_id,source_version_id,source_page,evidence_quote,
             valid_from,extraction_method,review_status)
            VALUES (%s,%s,'REFERS_TO',%s,%s,1,'Synthetic reference','2024-01-01','test','candidate')
            """,
            (relation, subject, obj, version),
        )
    repo = EvidenceRepository(conn)
    allowed = {source, target}
    assert repo.graph_neighbors([source], allowed, date(2026, 1, 1)) == []
    with conn.cursor() as cur:
        cur.execute("UPDATE kg_relations SET review_status='verified' WHERE id=%s", (relation,))
    assert repo.graph_neighbors([source], allowed, date(2024, 6, 1)) == []
    assert repo.graph_neighbors([source], {source}, date(2026, 1, 1)) == []
    assert repo.graph_neighbors([source], allowed, date(2026, 1, 1))[0]["target"] == target


def test_quoted_proposals_require_review_and_keep_history(conn):
    from ingestion.graph.review import Proposal, review, stage

    source = "TEST/REVIEW/" + str(uuid4())
    _, version = seed(conn, source)
    proposal = Proposal(
        source_version_id=version,
        source_page=1,
        predicate="REQUIRES",
        label="Maintain minimum ratio",
        evidence_quote="The minimum ratio is 15 percent.",
    )
    relation = stage(conn, proposal)
    repo = EvidenceRepository(conn)
    assert repo.graph_evidence("minimum ratio", [source], {source}, date(2025, 1, 1), 5) == []
    assert (
        conn.execute("SELECT review_status FROM kg_relations WHERE id=%s", (relation,)).fetchone()[
            0
        ]
        == "candidate"
    )
    review(
        conn, relation, "candidate", "verified", "test-reviewer", "Synthetic quoted fixture checked"
    )
    assert stage(conn, proposal) == relation
    evidence = repo.graph_evidence("minimum ratio", [source], {source}, date(2025, 1, 1), 5)
    assert [(item["predicate"], item["target_kind"], item["source_page"]) for item in evidence] == [
        ("REQUIRES", "obligation", 1)
    ]
    assert repo.graph_evidence("minimum ratio", [source], set(), date(2025, 1, 1), 5) == []
    assert (
        conn.execute("SELECT review_status FROM kg_relations WHERE id=%s", (relation,)).fetchone()[
            0
        ]
        == "verified"
    )
    assert (
        conn.execute(
            "SELECT count(*) FROM kg_relation_reviews WHERE relation_id=%s", (relation,)
        ).fetchone()[0]
        == 1
    )
    with pytest.raises(ValueError, match="state changed"):
        review(conn, relation, "candidate", "rejected", "test-reviewer", "Stale review")
    review(conn, relation, "verified", "rejected", "test-reviewer", "Retract synthetic review")
    assert repo.graph_evidence("minimum ratio", [source], {source}, date(2025, 1, 1), 5) == []
    assert (
        conn.execute(
            "SELECT count(*) FROM kg_relation_reviews WHERE relation_id=%s", (relation,)
        ).fetchone()[0]
        == 2
    )


def test_proposal_rejects_invented_quote(conn):
    from ingestion.graph.review import Proposal, stage

    _, version = seed(conn, "TEST/REVIEW/" + str(uuid4()))
    proposal = Proposal(
        source_version_id=version,
        source_page=1,
        predicate="REQUIRES",
        label="Invented rule",
        evidence_quote="The minimum ratio is 99 percent.",
    )
    with pytest.raises(ValueError, match="exactly"):
        stage(conn, proposal)
