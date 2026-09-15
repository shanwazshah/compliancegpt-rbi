-- Invalidate caches on all committed evidence/graph edits, including review changes.
CREATE OR REPLACE FUNCTION bump_evidence_revision() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    UPDATE evidence_revision SET revision=revision+1 WHERE singleton;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS document_versions_revision ON document_versions;
CREATE TRIGGER document_versions_revision AFTER INSERT OR UPDATE OR DELETE ON document_versions
FOR EACH STATEMENT EXECUTE FUNCTION bump_evidence_revision();

DROP TRIGGER IF EXISTS evidence_pages_revision ON evidence_pages;
CREATE TRIGGER evidence_pages_revision AFTER INSERT OR UPDATE OR DELETE ON evidence_pages
FOR EACH STATEMENT EXECUTE FUNCTION bump_evidence_revision();

DROP TRIGGER IF EXISTS document_nodes_revision ON document_nodes;
CREATE TRIGGER document_nodes_revision AFTER INSERT OR UPDATE OR DELETE ON document_nodes
FOR EACH STATEMENT EXECUTE FUNCTION bump_evidence_revision();

DROP TRIGGER IF EXISTS kg_entities_revision ON kg_entities;
CREATE TRIGGER kg_entities_revision AFTER INSERT OR UPDATE OR DELETE ON kg_entities
FOR EACH STATEMENT EXECUTE FUNCTION bump_evidence_revision();

DROP TRIGGER IF EXISTS kg_relations_revision ON kg_relations;
CREATE TRIGGER kg_relations_revision AFTER INSERT OR UPDATE OR DELETE ON kg_relations
FOR EACH STATEMENT EXECUTE FUNCTION bump_evidence_revision();
