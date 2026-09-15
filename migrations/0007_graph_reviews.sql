-- Local operator review history; graph relations remain candidates until reviewed.
CREATE TABLE IF NOT EXISTS kg_relation_reviews (
    id BIGSERIAL PRIMARY KEY,
    relation_id UUID NOT NULL REFERENCES kg_relations(id),
    previous_status TEXT NOT NULL CHECK (previous_status IN ('candidate','verified','rejected')),
    new_status TEXT NOT NULL CHECK (new_status IN ('candidate','verified','rejected')),
    reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_kg_reviews_relation ON kg_relation_reviews(relation_id);
