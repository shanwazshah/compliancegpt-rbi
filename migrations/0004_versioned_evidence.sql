-- Canonical evidence is independent of Qdrant. Legal validity is explicit.
CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id),
    content_hash TEXT NOT NULL,
    pdf_path TEXT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_from DATE NOT NULL,
    valid_to DATE,
    validity_basis TEXT NOT NULL CHECK (validity_basis IN ('observed_at', 'verified')),
    parser_version TEXT NOT NULL,
    index_kind TEXT NOT NULL DEFAULT 'pages' CHECK (index_kind IN ('pages', 'pageindex')),
    index_metadata JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(document_id, content_hash, valid_from),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS idx_versions_validity
    ON document_versions(document_id, valid_from, valid_to);

CREATE TABLE IF NOT EXISTS evidence_pages (
    version_id UUID NOT NULL REFERENCES document_versions(id),
    page_number INT NOT NULL CHECK (page_number >= 1),
    printed_label TEXT,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    PRIMARY KEY(version_id, page_number)
);
CREATE INDEX IF NOT EXISTS idx_evidence_page_search
    ON evidence_pages USING GIN(to_tsvector('english', text));

CREATE TABLE IF NOT EXISTS document_nodes (
    version_id UUID NOT NULL REFERENCES document_versions(id),
    node_id TEXT NOT NULL,
    parent_id TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    page_start INT NOT NULL,
    page_end INT NOT NULL,
    PRIMARY KEY(version_id, node_id),
    FOREIGN KEY(version_id, page_start) REFERENCES evidence_pages(version_id, page_number),
    FOREIGN KEY(version_id, page_end) REFERENCES evidence_pages(version_id, page_number),
    FOREIGN KEY(version_id, parent_id) REFERENCES document_nodes(version_id, node_id)
        DEFERRABLE INITIALLY DEFERRED,
    CHECK (page_end >= page_start)
);

-- A published revision changes cache keys only when an ingestion transaction commits.
CREATE TABLE IF NOT EXISTS evidence_revision (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    revision BIGINT NOT NULL DEFAULT 0
);
INSERT INTO evidence_revision(singleton) VALUES (TRUE) ON CONFLICT DO NOTHING;
