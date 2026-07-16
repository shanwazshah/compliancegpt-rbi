-- Migration 0002 — query logs for observability / cost tracking (spec §9, §16).
-- Adapted to what the Phase 2 agent actually produces: citations are stored as
-- doc_numbers (TEXT[]) rather than chunk UUIDs. Query text is PII-redacted before
-- insertion (see app/observability/redaction.py) — no raw account/ID numbers land here.

CREATE TABLE IF NOT EXISTS query_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_text TEXT NOT NULL,             -- already PII-redacted
    reference_date DATE,
    in_force_docs INT,
    cited_doc_numbers TEXT[],
    answer_text TEXT,
    degraded BOOLEAN,
    verified_citations BOOLEAN,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_logs_created_at ON query_logs (created_at);
