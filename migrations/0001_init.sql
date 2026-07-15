-- Migration 0001 — Phase 0 core tables.
-- Only the two tables the temporal-correctness feature is built on:
--   documents            : one row per regulatory document
--   supersession_edges   : directed graph of which doc replaces/amends which
-- The remaining tables from PROJECT_SPEC.md §9 (chunks, golden_qa, eval_runs,
-- query_logs) are added in later phases when they are first needed.
--
-- gen_random_uuid() is built into PostgreSQL 13+ core, so no extension needed.

-- One row per regulatory document (circular, master direction, master circular)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_regulator TEXT NOT NULL CHECK (source_regulator IN ('RBI', 'SEBI')),
    doc_type TEXT NOT NULL,               -- 'circular' | 'master_direction' | 'master_circular' | 'notification'
    doc_number TEXT NOT NULL,             -- e.g. 'RBI/DoR/2025-26/XX'
    title TEXT NOT NULL,
    issue_date DATE NOT NULL,
    effective_date DATE,
    status TEXT NOT NULL DEFAULT 'active' -- 'active' | 'superseded' | 'withdrawn' | 'draft'
        CHECK (status IN ('active', 'superseded', 'withdrawn', 'draft')),
    source_url TEXT NOT NULL,
    pdf_storage_path TEXT,
    entity_categories TEXT[],             -- e.g. {'NBFC','Commercial Banks'}
    subject_tags TEXT[],
    raw_text_hash TEXT,                   -- for idempotent re-ingestion / change detection
    ingested_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes that the temporal pre-filter and lookups will rely on.
CREATE INDEX IF NOT EXISTS idx_documents_issue_date   ON documents (issue_date);
CREATE INDEX IF NOT EXISTS idx_documents_status       ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_regulator    ON documents (source_regulator);
CREATE INDEX IF NOT EXISTS idx_documents_entity_cats  ON documents USING GIN (entity_categories);
-- Prevent accidental duplicate ingestion of the same document.
CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_regulator_docnumber
    ON documents (source_regulator, doc_number);

-- Directed graph of which documents replace / amend / consolidate which
CREATE TABLE IF NOT EXISTS supersession_edges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    predecessor_doc_id UUID REFERENCES documents(id),   -- older document
    successor_doc_id UUID REFERENCES documents(id),     -- newer document
    relation_type TEXT NOT NULL                         -- 'supersedes' | 'amends' | 'consolidates' | 'partially_supersedes'
        CHECK (relation_type IN ('supersedes', 'amends', 'consolidates', 'partially_supersedes')),
    effective_date DATE,
    extraction_confidence FLOAT,
    extraction_method TEXT,               -- 'llm_extracted' | 'manual_verified' | 'rbi_explicit_list'
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_edges_predecessor ON supersession_edges (predecessor_doc_id);
CREATE INDEX IF NOT EXISTS idx_edges_successor   ON supersession_edges (successor_doc_id);
