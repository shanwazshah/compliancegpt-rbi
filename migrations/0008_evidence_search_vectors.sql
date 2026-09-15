-- Store page search vectors once and index them for local vectorless retrieval.
ALTER TABLE evidence_pages
    ADD COLUMN IF NOT EXISTS search_vector tsvector
    GENERATED ALWAYS AS (to_tsvector('english', COALESCE(text, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_evidence_pages_search_vector
    ON evidence_pages USING GIN (search_vector);