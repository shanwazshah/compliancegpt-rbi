# Advanced RAG implementation — first increment

Implemented on 2026-09-05 against the approved [plan](ADVANCED_RAG_PLAN.md).
This is a working code increment with isolated API/retrieval tests, not a claim that the full advanced-RAG roadmap or live corpus evaluation is complete.

## What is implemented

- Canonical evidence schema: document versions, physical pages, section trees and corpus revision tracking, independent of Qdrant.
- Immutable PDF snapshots addressed by SHA-256; page text and parser version are cached with the snapshot.
- Optional official PageIndex 0.2.10 local adapter. The downloaded SDK was checked directly: this release exposes PageIndexLocalClient without the newer mode= constructor parameter.
- Retrieval modes: lexical, pageindex and graph_pageindex, alongside the original vector strategies. Vector imports are lazy and the embedding packages are optional extras.
- Bounded tree traversal validates model-selected IDs against the permitted tree. Source reads use canonical local page text. Missing trees and invalid selections fail visibly instead of silently falling back to vectors.
- A typed graph schema and deterministic, source-backed document REFERS_TO ingestion. graph_pageindex follows up to two hops of verified, date-valid references. Obligations and exceptions have schema support but their extraction/review workflow is not implemented yet.
- Page evidence IDs in prompts and citations, evidence inspection/tree endpoints, strategy selection, source text, and graph paths in the API and development UI.
- Exact response caching keyed by resolved date, corpus revision, route and model/prompt settings; no embedding-based cache lookup.
- Foundation repairs: production API-key forwarding, anonymous rate-limit bypass, date validation, partial-amendment document handling, future commencement/draft filtering, distinct parent windows, numerical-grounding checks, PII-redacted answer logging and returned query-log IDs.
- Package discovery includes nested modules. Docker copies packages before installing. Vectorless builds can omit torch. Readiness returns 503 when required backing services are unavailable.
- PDF parse-cache invalidation and removal of obsolete vector chunk IDs after successful replacement. An embedding dimension mismatch now requires a separate named collection rather than automatically deleting the old one.
- A checksum-based transactional migration runner and a dedicated vectorless CI lane.

## Local setup

Run commands from the repository root. Keep the original .venv for the vector baseline. A separate tested environment has been created locally at data/vectorless-env; it is ignored by Git.

For a fresh environment:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -c constraints/vectorless-py312.txt -e ".[dev,pageindex]"
```

The constraints file records the tested Windows Python 3.12 environment. Linux installation is covered by the added CI job but has not run locally. To retain dense/hybrid retrieval, install the vector extra as well: `pip install -e ".[dev,vector,pageindex]"`.

Start PostgreSQL using ONE local stack, to avoid competing for port 5432:

```powershell
docker compose -f docker-compose.vectorless.yml up -d
.venv\Scripts\python.exe -m ingestion.migrate
```

The vectorless stack binds Postgres to localhost and shares the default Compose project volume name with the existing development stack. It does not launch Qdrant. On an existing database, migrations 0004 through 0006 add the evidence/graph tables and revision triggers. Existing idempotent migrations are adopted into the migration ledger the first time the runner is used; future checksum changes are rejected.

Configure LLM_PROVIDER, LLM_MODEL, LLM_MODEL_FAST, LLM_BASE_URL and LLM_API_KEY in .env. No secret values were changed. The PageIndex index adapter currently uses the configured OpenAI-compatible backend. Set PAGEINDEX_INDEX_MODEL to an explicit compatible model if needed; native Anthropic indexing configuration remains a follow-up.

## Pilot ingestion

Five existing PDFs were selected into data/pilot_manifest.json, including KYC. Their local immutable snapshots were successfully extracted:

| Document | Physical pages |
|---|---:|
| RBI/DOR/2025-26/361 | 96 |
| RBI/DOR/2025-26/339 | 31 |
| RBI/DOR/2025-26/340 | 11 |
| RBI/DoR/2025-26/341 | 5 |
| RBI/DOR/2025-26/342 | 8 |
| Total | 151 |

These snapshots contain 276,207 extracted characters. This verifies extraction and provenance storage on disk; it does not verify table reconstruction, legal correctness or PageIndex answer quality.

Once PostgreSQL is running:

```powershell
# Publish canonical page text; no LLM calls.
.venv\Scripts\python.exe -m ingestion.pageindex.ingest --manifest data/pilot_manifest.json --limit 5

# Add official trees; this calls the configured model and may incur provider charges.
.venv\Scripts\python.exe -m ingestion.pageindex.ingest --manifest data/pilot_manifest.json --limit 5 --pageindex

# Build literal source-backed cross-references.
.venv\Scripts\python.exe -m ingestion.graph.references
```

For a fresh clone without the generated pilot manifest, omit --manifest to use data/nbfc_manifest.json after running the existing scraper. The default limit is five documents.

Content validity defaults to the capture date. Use --valid-from YYYY-MM-DD only after verifying that the exact snapshot applied then. A current PDF containing later amendments is not automatically accepted as historical text merely because its original issue date is old. Old versions remain stored; applicable snapshot selection is deterministic. Provision-level amendment composition is a later milestone.

Set RETRIEVAL_STRATEGY=lexical to query published pages without PageIndex trees. After tree ingestion succeeds, use pageindex or graph_pageindex:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.venv\Scripts\python.exe -m streamlit run ui/streamlit_app.py
```

The API also accepts an explicit strategy:

```json
{
  "question": "What are the periodic KYC update requirements?",
  "reference_date": "2026-09-05",
  "strategy": "pageindex"
}
```

References use immutable evidence IDs. Inspect originals with GET /api/evidence/{version_id}/pages/{page_number} and trees with GET /api/evidence/{version_id}/tree. These inspection endpoints can display historical evidence; they do not assert that a page is currently applicable.

Production Docker now requires API_KEY as well as LLM_API_KEY. The existing production stack still includes Qdrant for compatibility; the separate vectorless development stack demonstrates the minimal database dependency.

## Verification and limitations

- Original environment: non-integration tests pass; the final count is recorded below.
- Clean vectorless environment: full API tests with deterministic model/repository fixtures pass. torch, sentence_transformers, qdrant_client and rank_bm25 are absent, and the real app imports successfully. pip check reports no broken requirements.
- Source lint and Python compilation pass.
- PageIndex constructor conformance was checked against the actual pinned wheel, not inferred from newer documentation.
- PostgreSQL 16 is healthy in the local vectorless Docker stack. All six migrations were applied; a second migration run completed without changes. All 144 tests passed, including seven PostgreSQL integration tests.
- All five pilot versions and 151 pages are published in PostgreSQL. Repeat ingestion reused the same version IDs. Live lexical retrieval returned KYC page 43 for the periodic-update query, and its evidence endpoint returned HTTP 200 in the clean vectorless environment. This smoke check does not measure retrieval precision.
- Literal reference ingestion completed and found zero cross-reference edges among the five pilot documents. No PageIndex trees are published. A read-only provider authentication check returned HTTP 401; update LLM_API_KEY in the local .env before indexing or live answer generation. No secret values were changed or printed, and no paid indexing/generation calls were made.
- PostgreSQL integration tests cover snapshot selection, commencement, partial amendments, graph review state and source-version validity and now pass against the local database.
- The previous saved generation evaluation still fails its citation-accuracy floor. It has not been relabeled as a result for this implementation.

## Remaining roadmap

1. Correct the local provider credentials, publish the official PageIndex pilot trees, and verify live tree navigation and citations.
2. Profile indexing and retrieval with the configured live model before widening the corpus.
3. Add reviewed obligation/exception extraction, provision-level legal validity and applicability conditions. The current graph retrieval is document cross-reference traversal, not a complete regulatory knowledge graph.
4. Improve tree navigation for long leaf ranges and expose explicit coverage/budget-exhaustion metadata. Current retrieval is bounded and may omit relevant pages; it is not an exhaustive-checklist engine.
5. Replace lexical groundedness with stronger claim-support checks. The numeric guard catches new quantities, but matching numbers or word overlap do not prove entailment or resolve negation.
6. Add historical source text, answerable temporal holdout questions, current-commit evaluation artifacts, and route-specific cost/latency comparisons before changing the default route.

This increment preserves the user's earlier PROJECT_SPEC.md edits and embedding-model defaults. No commits or deployments were made.

Final validation: 144 tests passed, including all seven PostgreSQL integration tests. In the clean vectorless environment, all 27 advanced tests previously passed; real database ingestion, lexical retrieval and evidence endpoint smoke checks now also pass. Ruff, pip check, wheel build and nested-module packaging checks passed in the preceding implementation run.

## Live provider retry — 2026-09-07

The updated Groq credentials authenticated successfully. The configured Llama model IDs were absent from the account model list. A completion with openai/gpt-oss-20b succeeded; LLM_MODEL and LLM_MODEL_FAST in the local .env now use that model.

The five-page voluntary-amalgamation PDF (RBI/DoR/2025-26/341) was successfully indexed with the official PageIndex adapter, upgrading its existing September 5 snapshot. Live tree navigation returned physical pages 2–4. This verifies indexing and retrieval, not answer correctness.

The remaining batch encountered HTTP 429 at the provider-reported 8,000 tokens/minute limit. It was interrupted because SDK retries were too rapid. Remaining work: add provider-aware pacing and bounded backoff before resuming the other four PDFs; then verify complete answers and citations. No billing changes were made.

## Rate-aware indexing — 2026-09-07

The adapter now scopes a paced OpenAI-compatible completion transport to the pinned PageIndex 0.2.10 SDK. Sync and async indexing requests share a lock. Calls wait at least PAGEINDEX_MIN_INTERVAL_SECONDS (default 20) after a response; HTTP 429 and transient failures respect Retry-After seconds/date headers or Groq duration messages, with exponential fallback. PAGEINDEX_MAX_ATTEMPTS defaults to 4, and retry waits exceeding PAGEINDEX_MAX_RETRY_WAIT_SECONDS (120) stop the operation. Authentication/configuration failures stop immediately. No account or billing settings are changed.

Successful completions are stored under data/pageindex/completion_cache with SHA-256 request keys including endpoint, model and message content. These local files contain model output derived from source text. Resuming the same request reuses them, avoiding repeated successful provider calls after an interruption. This is a local ingestion cache, not the answer cache. It does not coordinate separate processes or other applications using the same account quota; run one indexing command at a time. Individual requests exceeding the provider quota still fail and require smaller SDK input batches or a different provider limit.

The SDK lacks a public completion hook, so this adapter temporarily replaces its two completion helpers and imported aliases, guarded by an exact SDK version check and a process lock. All aliases are restored afterwards. Transport failure rejects publication even if an SDK layer absorbs it. No installed dependency files are modified. Tests cover retry spacing, cache reuse, attempt limits, terminal failures, provider duration parsing and hook restoration.

## Pilot completion and transport fixes — 2026-09-09

PostgreSQL restarted successfully. All five pilot PDFs now have published PageIndex trees: Registration 27 nodes, Acquisition 8, Voluntary Amalgamation 2, Branch Authorisation 10, KYC 41; total 88 nodes over the existing 151 canonical pages. The first four use LLM-refined SDK trees. KYC uses the official PageIndex Flash layout extractor with summary=False and optimize=False, explicitly recorded as tree_mode=layout and summaries=false in its version metadata. This is a real local layout-derived PageIndex tree, not an LLM-refined KYC index.

Groq accepted the configured key and model, and a live regulatory-scope classification succeeded. KYC full refinement encountered empty completions and then an oversized request (HTTP 413). The transport now retries empty replies within its existing attempt limits, preserves sanitized failures even when the SDK wraps them, and sets an explicit PAGEINDEX_MAX_OUTPUT_TOKENS (default 4096). Request cache keys include that output budget. No truncated or failed KYC full tree was published.

Use --pageindex --tree-mode layout when explicitly choosing local layout extraction. Full remains the default; there is no silent mode fallback. Existing published versions remain cached, so selecting another mode alone does not rebuild an existing tree. LLM summaries and large-section refinement for KYC remain future work; downstream navigation can use its detected headings and canonical page text today.

A new explicit live smoke runner, python -m evals.pilot_smoke --question ... --strategy pageindex --date YYYY-MM-DD --output data/evals/report.json, records the API result and checks citation page endpoints. It does not measure entailment or completeness. Historical content validity remains September 5 for these already-captured snapshots, rather than resetting it to each indexing date.

## Citation and continuation-page repairs

The first live KYC smoke check exposed two defects: competing citation instructions and page budgets allocated to empty document selections. Generation prompt gen-v6 now requires the exact supplied citation value, and retrieval distributes its total page budget across documents that actually return evidence. This preserves the KYC continuation page containing the requested intervals. Known wrapper syntax around an E: identifier is normalized to square brackets without altering the identifier; unknown IDs remain visible to the verifier and are rejected. Answers with page evidence but no recognized page citation now fail verification instead of appearing verified. This is citation-location validation, not claim entailment.

The smoke runner now exits unsuccessfully for missing/invalid citations or unresolved evidence endpoints, even when the query HTTP status is 200. Earlier failed reports remain saved separately (pilot_pageindex_smoke.json and pilot_pageindex_smoke_v4.json); they are not successful evaluation results.

A captured live completion used whitespace inside its citation brackets (`[ E:...:41 ]`). The output normalizer now removes only citation wrapper syntax/whitespace, retaining the exact identifier for validation. Replaying that captured output resolves KYC page 41 correctly; regression tests cover known IDs, unknown IDs, absent citations, decorative brackets and whitespace. The broad suite passed 156 tests with three SDK-dependent skips in the original environment; the final whitespace-specific retrieval/generation suite passed 14 tests in the clean vectorless environment.

## Verified live citation smoke and graph review foundation — 2026-09-10

Prompt/cache version gen-v7 also normalizes the model's `[citation: E:...]` wrapper while preserving the exact identifier. The live PageIndex API smoke check now passes: HTTP 200, non-degraded answer, one verified citation, six retrieved KYC pages, and HTTP 200 for cited physical page 41. The answer states the three requested update intervals found on that page. Recorded output: data/evals/pilot_pageindex_smoke_v7.json. This is one successful integration check, not a holdout score or a completeness guarantee; the page also contains an exception requiring separate applicability analysis.

Migration 0007 adds graph review history. The new ingestion.graph.review CLI stages exact-source-quoted candidates and records explicit review transitions with stale-state protection. Two KYC obligation/exception proposals are staged, not approved or used in retrieval. See GRAPH_REVIEW.md. Real database tests cover invented-quote rejection, idempotent restaging, persisted review history and stale review protection. The focused integration/retrieval suite passed 22 tests. No automatic legal verification is inferred from matching a quote.

Final validation for this increment: 162 tests passed, three SDK-dependent tests skipped in the original environment. The focused integration/retrieval suite passed all 22 tests in the vectorless environment. Changed-source lint passed.

## Local retrieval benchmark and runtime hardening — 2026-09-14

PageIndex navigation is now local-first. The default `PAGEINDEX_NAVIGATION_MODE=local`
uses PostgreSQL lexical anchors plus stored PageIndex section boundaries, titles and
summaries. It expands around the strongest physical page inside the narrowest matching
section and adds locally ranked sections. It makes no runtime model call and has no
vector dependency. `PAGEINDEX_NAVIGATION_MODE=llm` remains an explicit optional mode.
Hosted navigation is bounded to one document tree by default, uses a 30-second request
timeout and disables hidden client retries.

Migration 0008 stores each page's English `tsvector` and adds a GIN index. Query cleanup
removes corpus-wide terms such as RBI and NBFC before ranking. On this Windows host,
using IPv4 loopback also removed a five-second `localhost` connection delay. Candidate
selection fell from roughly 5.2 seconds to 9–75 milliseconds in the measured miss cases.

The locked pilot dataset contains 15 source-location-checked questions across all five
pilot documents. It tests retrieval and immutable evidence resolution; it has not been
reviewed as a legal-answer correctness or completeness set.

| Route | Document recall@8 | Physical-page recall@8 | Evidence resolution | p95 latency |
|---|---:|---:|---:|---:|
| lexical | 15/15 (100%) | 12/15 (80%) | 120/120 (100%) | 112.70 ms |
| pageindex (local) | 15/15 (100%) | 15/15 (100%) | 120/120 (100%) | 121.01 ms |
| graph_pageindex (local) | 15/15 (100%) | 15/15 (100%) | 120/120 (100%) | 122.39 ms |

Artifacts are stored in `data/evals/advanced_lexical_k8_v3.json`,
`data/evals/advanced_pageindex_local_k8_v2.json` and
`data/evals/advanced_graph_pageindex_local_k8_v1.json`. The graph route currently ties
plain PageIndex because the two source-quoted KYC graph proposals remain candidates.
They are excluded until a named reviewer verifies or rejects them.

The full suite passes 174 tests with three SDK-dependent skips. Project-wide Ruff and
Git whitespace checks pass. Remaining release work is broader independent legal review,
verified obligation/exception graph coverage, historical-version holdouts, stronger
claim entailment checks, and production operations/security validation.

### Frozen internal holdout

After freezing the ranking and navigation changes, a second ten-question dataset using
different checked page locations was run once. Lexical, local PageIndex and local
graph_pageindex all retrieved the correct document in 10/10 cases and the exact checked
physical page in 9/10. Every returned evidence ID resolved. PageIndex p95 was 99.86 ms.
All three missed the KYC onboarding-rejection rule on page 20; PageIndex returned adjacent
page 19. No retrieval change was made after this result. The holdout was checked by the
implementer and still requires independent regulatory review.
