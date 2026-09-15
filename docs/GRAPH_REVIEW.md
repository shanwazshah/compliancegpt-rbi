# Source-quoted graph review

The local CLI can stage obligations, exceptions, definitions and applicability proposals. Staging verifies that each quote occurs exactly on its cited immutable page, inherits that snapshot's validity interval and marks the relation `candidate`. This proves provenance, not legal correctness. Concepts are scoped to their source document.

Ten pilot proposals are in `ingestion/graph/pilot_proposals.json`: two KYC, three registration, one acquisition/control, one voluntary-amalgamation and three branch-authorisation relations. Each proposal uses an exact quote from a canonical physical page. All ten are candidates; none has been approved. Review the complete surrounding section, dates and applicability before accepting any proposal.

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m ingestion.graph.review stage ingestion/graph/pilot_proposals.json
.venv\Scripts\python.exe -m ingestion.graph.review list --status candidate
.venv\Scripts\python.exe -m ingestion.graph.review export data/graph/pilot_review_packet.md --status candidate
```

A trusted local operator records an actual review using:

```text
python -m ingestion.graph.review review RELATION_UUID --expected candidate --status verified --reviewer YOUR_NAME --reason "Describe the source and applicability checks performed"
```

Use `rejected` to reject and `candidate` to reopen an existing decision, with the actual current value in `--expected`. Concurrent/stale review attempts fail. Status and history are written in the caller's database transaction. Restaging an identical proposal never overwrites its review decision. The history records previous/new status, reviewer, reason and time. The reviewer is an operator-supplied label, not authenticated identity; this CLI assumes trusted local database access.

`graph_pageindex` now searches verified `REQUIRES`, `HAS_EXCEPTION`, `DEFINES` and `APPLIES_TO` relations, prioritises their cited source pages and still enforces document/date scope. Candidate and rejected relations never enter retrieval. The current graph benchmark ties plain PageIndex because all ten pilot concepts remain candidates; it validates review-state isolation, not graph quality or completeness.
