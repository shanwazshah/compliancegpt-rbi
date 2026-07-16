# Retrieval Ablation — dense vs BM25 vs hybrid

- Date: 2026-07-16
- Golden set: 26 answerable questions · K=5

| Strategy | Recall@5 | MRR |
|---|---|---|
| dense | 92.3% | 0.811 |
| bm25 | 92.3% | 0.655 |
| hybrid | 92.3% | 0.728 |

## Per-question rank of the expected doc (K=5, MISS = not in top 5)

| Question | dense | bm25 | hybrid |
|---|---|---|---|
| What is the periodic KYC updation cycle for a low-risk  | 1 | 1 | 1 |
| How often must an NBFC carry out re-KYC for high-risk c | 1 | 1 | 1 |
| What is the periodic updation interval for medium-risk  | 1 | 1 | 1 |
| Which Master Direction governs the issuance and conduct | 1 | 2 | 1 |
| What rules apply to an NBFC accepting public deposits? | 1 | 2 | 1 |
| Where are the capital adequacy prudential norms for NBF | MISS | 2 | MISS |
| What governs the declaration of dividends by an NBFC? | 1 | 5 | 1 |
| Which direction covers microfinance loans provided by N | 2 | 4 | 3 |
| What framework applies to a peer-to-peer lending platfo | 1 | 1 | 1 |
| How are NBFCs classified under scale-based regulation? | 1 | 1 | 1 |
| What are the income recognition and asset classificatio | 4 | 4 | 4 |
| Which direction governs resolution of stressed assets f | 1 | 4 | 4 |
| How does the RBI treat wilful defaulters and large defa | 1 | 1 | 1 |
| What are the requirements for an NBFC outsourcing arran | 1 | 1 | 1 |
| Which direction covers climate change risk management f | 1 | 1 | 1 |
| What governance framework applies to NBFC boards? | 2 | MISS | 4 |
| What are the rules for an NBFC acquiring shareholding o | 1 | 1 | 1 |
| Which direction governs securitisation transactions und | 1 | 2 | 1 |
| What norms cover asset-liability management for NBFCs? | 1 | 1 | 1 |
| What applies to an NBFC operating as an Account Aggrega | 1 | 2 | 2 |
| Does an NBFC need authorisation to open a new branch? | 1 | 1 | 1 |
| What are the credit information reporting obligations o | MISS | 3 | MISS |
| Which direction governs concentration risk (large expos | 1 | 1 | 1 |
| What responsible business conduct requirements apply to | 2 | 4 | 2 |
| How must an NBFC present its financial statements and d | 3 | 1 | 2 |
| Can two NBFCs voluntarily amalgamate, and what governs  | 1 | MISS | 3 |