-- Migration 0003 — real supersession data, eval history, and cost tracking.
--
-- Three separable concerns, all needed before the project can report its
-- headline numbers honestly:
--
--   1. documents.withdrawn_date / issue_date_precision
--      RBI publishes an official "Circulars Withdrawn" list. That a circular WAS
--      withdrawn is ground truth; WHICH Master Direction replaced it is inferred.
--      Storing the withdrawal fact on the document keeps those two claims apart:
--      the temporal filter can retire a circular on RBI's authority alone, even
--      when we cannot confidently name its successor. Previously the filter could
--      only retire a document via a supersession edge, so an unmatched circular
--      would have stayed "in force" forever.
--
--      issue_date_precision records HOW we know a document's issue date, because
--      the withdrawn-circulars listing publishes LAST-UPDATED dates, not issue
--      dates. Temporal correctness is computed against issue dates, so date
--      provenance is a first-class fact rather than a footnote.
--
--   2. eval_runs (spec §9) — one row per eval run. This is what makes
--      "eval-gated CI" demonstrable rather than aspirational: CI writes a row and
--      compares against committed thresholds.
--
--   3. query_logs cost/quality columns — per-query token cost and groundedness,
--      so "$X per query" and "p95 latency" are measured, not estimated.

-- ---- 1. document-level withdrawal facts -------------------------------------

ALTER TABLE documents ADD COLUMN IF NOT EXISTS withdrawn_date DATE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS issue_date_precision TEXT
    DEFAULT 'exact'
    CHECK (issue_date_precision IN ('exact', 'detail_page', 'fiscal_year_estimate',
                                    'listing_fallback'));

COMMENT ON COLUMN documents.withdrawn_date IS
    'Date the regulator withdrew this document (ground truth from RBI''s published list).';
COMMENT ON COLUMN documents.issue_date_precision IS
    'Provenance of issue_date. fiscal_year_estimate = lower bound derived from the '
    'circular number''s fiscal year, not a verified date.';

-- The temporal pre-filter scans on these together.
CREATE INDEX IF NOT EXISTS idx_documents_withdrawn_date ON documents (withdrawn_date);

-- ---- 2. eval history --------------------------------------------------------

CREATE TABLE IF NOT EXISTS eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    git_commit_sha TEXT,
    run_at TIMESTAMPTZ DEFAULT now(),
    retrieval_strategy TEXT,              -- 'dense' | 'bm25' | 'hybrid' | 'hybrid_rerank'
    golden_set_size INT,                  -- rows actually scored (excludes skips)
    -- retrieval metrics
    recall_at_5 FLOAT,
    mrr FLOAT,
    -- project-specific metrics (spec §14) — the ones that differentiate this build
    citation_accuracy FLOAT,
    temporal_correctness FLOAT,
    refusal_correctness FLOAT,
    -- generation quality (NULL when the judge was unavailable — never 0.0, see
    -- docs/adr/0007: scoring a failed judge call as zero understates quality)
    faithfulness FLOAT,
    answer_relevancy FLOAT,
    raw_results_path TEXT,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_eval_runs_run_at ON eval_runs (run_at DESC);

-- ---- 3. per-query cost & quality -------------------------------------------

ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS prompt_tokens INT;
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS completion_tokens INT;
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS token_cost NUMERIC(12, 8);
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS groundedness_score FLOAT;
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS cache_hit BOOLEAN DEFAULT false;
ALTER TABLE query_logs ADD COLUMN IF NOT EXISTS llm_model TEXT;

-- ---- 4. opt-in feedback (spec §12) ----------------------------------------
-- Opt-in only, and the comment is PII-redacted before insertion exactly like
-- query_text (spec §16: no PII beyond the query text itself).

CREATE TABLE IF NOT EXISTS query_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_log_id UUID NOT NULL REFERENCES query_logs(id) ON DELETE CASCADE,
    rating INT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,                         -- already PII-redacted
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_query_feedback_log ON query_feedback (query_log_id);
