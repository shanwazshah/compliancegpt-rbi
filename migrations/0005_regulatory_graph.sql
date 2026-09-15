-- Source-backed typed graph; extraction is not automatic legal authority.
CREATE TABLE IF NOT EXISTS kg_entities (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN (
        'document', 'provision', 'entity_class', 'defined_term', 'obligation', 'exception'
    )),
    canonical_name TEXT NOT NULL,
    aliases TEXT[] NOT NULL DEFAULT '{}',
    UNIQUE(kind, canonical_name)
);
CREATE TABLE IF NOT EXISTS kg_relations (
    id UUID PRIMARY KEY,
    subject_id UUID NOT NULL REFERENCES kg_entities(id),
    predicate TEXT NOT NULL CHECK (predicate IN (
        'REFERS_TO', 'APPLIES_TO', 'DEFINES', 'REQUIRES', 'HAS_EXCEPTION',
        'AMENDS', 'SUPERSEDES'
    )),
    object_id UUID NOT NULL REFERENCES kg_entities(id),
    source_version_id UUID NOT NULL,
    source_page INT NOT NULL,
    evidence_quote TEXT NOT NULL CHECK (length(evidence_quote) > 0),
    valid_from DATE NOT NULL,
    valid_to DATE,
    extraction_method TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('candidate', 'verified', 'rejected')),
    attributes JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY(source_version_id, source_page)
        REFERENCES evidence_pages(version_id, page_number),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
);
CREATE INDEX IF NOT EXISTS idx_kg_subject ON kg_relations(subject_id);
CREATE INDEX IF NOT EXISTS idx_kg_object ON kg_relations(object_id);
