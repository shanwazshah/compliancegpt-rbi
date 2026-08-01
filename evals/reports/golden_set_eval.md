# Golden-Set Eval

- Date: 2026-08-01
- Commit: `a396fb22173b`
- Generation model: `llama3.2` (classify: `llama3.2`)
- Embeddings: `BAAI/bge-small-en-v1.5`
- Retrieval strategy: dense
- Golden set: 95 rows ({'easy': 8, 'medium': 28, 'hard': 1, 'adversarial_temporal': 48, 'out_of_scope': 10})
- Row provenance: {'hand_written': 37, 'generated_from_rbi_withdrawn_index': 39, 'generated_from_md_issue_dates': 19}

## Headline metrics (spec §14)

| Metric | Value | Scored over |
|---|---|---|
| Citation accuracy | 73.7% | 19 citations |
| Temporal correctness | 100.0% | 48 date-scoped rows |
| Refusal correctness | 60.0% | 10 out-of-scope rows |
| Recall@5 | 94.6% | 37 answerable rows |
| MRR | 0.794 | 37 answerable rows |

## How temporal correctness is scored

A date-scoped row passes when the answer cites **no document that was not in
force at the reference date**. It is not required to cite the historical
document: the withdrawn predecessors are in the supersession graph, but their
PDFs are not chunked or embedded, so no retriever could return them. Scoring on
"did it find the old circular" would report a flat 0% that measures corpus
coverage rather than temporal reasoning.

### refusal_correctness — failures (4)

- What is the SEBI turnover fee for a stock broker?
- What is the minimum capital requirement for a payments bank?
- Draft a board resolution for my NBFC's KYC policy.
- What is my NBFC's current capital adequacy ratio?

## Per-question retrieval rank

| Question | Expected | Rank |
|---|---|---|
| What is the periodic KYC updation cycle for a low-risk ind | RBI/DOR/2025-26/361 | 1 |
| How often must an NBFC carry out re-KYC for high-risk cust | RBI/DOR/2025-26/361 | 1 |
| What is the periodic updation interval for medium-risk NBF | RBI/DOR/2025-26/361 | 1 |
| Which Master Direction governs the issuance and conduct of | RBI/DOR/2025-26/348 | 1 |
| What rules apply to an NBFC accepting public deposits? | RBI/DOR/2025-26/346 | 1 |
| Where are the capital adequacy prudential norms for NBFCs  | RBI/DOR/2025-26/345 | MISS |
| What governs the declaration of dividends by an NBFC? | RBI/DOR/2025-26/360 | 1 |
| Which direction covers microfinance loans provided by NBFC | RBI/DOR/2025-26/371 | 2 |
| What framework applies to a peer-to-peer lending platform  | RBI/DOR/2025-26/370 | 1 |
| How are NBFCs classified under scale-based regulation? | RBI/DOR/2025-26/339 | 1 |
| What are the income recognition and asset classification n | RBI/DOR/2025-26/356 | 4 |
| Which direction governs resolution of stressed assets for  | RBI/DOR/2025-26/357 | 1 |
| How does the RBI treat wilful defaulters and large default | RBI/DOR/2025-26/358 | 1 |
| What are the requirements for an NBFC outsourcing arrangem | RBI/DOR/2025-26/363 | 1 |
| Which direction covers climate change risk management for  | RBI/DOR/2025-26/364 | 1 |
| What governance framework applies to NBFC boards? | RBI/DOR/2025-26/344 | 2 |
| What are the rules for an NBFC acquiring shareholding or c | RBI/DOR/2025-26/340 | 1 |
| Which direction governs securitisation transactions undert | RBI/DOR/2025-26/353 | 1 |
| What norms cover asset-liability management for NBFCs? | RBI/DoR/2025-26/355 | 1 |
| What applies to an NBFC operating as an Account Aggregator | RBI/DoR/2025-26/368 | 1 |
| Does an NBFC need authorisation to open a new branch? | RBI/DOR/2025-26/342 | 1 |
| What are the credit information reporting obligations of a | RBI/DOR/2025-26/349 | MISS |
| Which direction governs concentration risk (large exposure | RBI/DOR/2025-26/351 | 1 |
| What responsible business conduct requirements apply to NB | RBI/DOR/2025-26/362 | 2 |
| How must an NBFC present its financial statements and disc | RBI/DOR/2025-26/359 | 3 |
| Can two NBFCs voluntarily amalgamate, and what governs it? | RBI/DoR/2025-26/341 | 1 |
| What are the current RBI requirements on peer to peer lend | RBI/DOR/2025-26/370 | 1 |
| Which Master Direction currently governs acceptance of pub | RBI/DOR/2025-26/346 | 1 |
| Which Master Direction currently governs account aggregato | RBI/DoR/2025-26/368 | 1 |
| What are the current RBI requirements on securitisation tr | RBI/DOR/2025-26/353 | 1 |
| What are the current RBI requirements on miscellaneous for | RBI/DOR/2025-26/373 | 5 |
| Which Master Direction currently governs acquisition of sh | RBI/DOR/2025-26/340 | 1 |
| Which Master Direction currently governs governance for NB | RBI/DOR/2025-26/344 | 3 |
| What are the current RBI requirements on credit risk manag | RBI/DOR/2025-26/350 | 1 |
| Which Master Direction currently governs know your custome | RBI/DOR/2025-26/361 | 2 |
| What are the current RBI requirements on asset liability m | RBI/DoR/2025-26/355 | 1 |
| Which Master Direction currently governs prudential norms  | RBI/DOR/2025-26/345 | 4 |
