# Generation-Quality Metrics (LLM-as-judge)

- Date: 2026-07-16
- Sample: 6 answerable questions
- **Faithfulness: 0.00** (scored 0/6)  ·  **Answer relevancy: 0.00** (scored 0/6)
- ⚠️ **6/6 generations FAILED** (LLM rate limit) and are excluded — these numbers are not a valid quality measurement. Re-run when the quota resets.
- Judge model: `llama-3.1-8b-instant` (independent of the generator, which avoids
  the generator grading its own work).
- Judge failures are reported as `n/a` and EXCLUDED from the mean — scoring
  a failed judge call as 0.0 would silently understate quality (this bug
  produced a fake 0.67 before it was caught).
- Caveat: the judge is a *smaller* model; a stronger judge validated against
  human-scored answers is the rigorous path (spec §14).

| Question | faithfulness | relevancy |
|---|---|---|
| What is the periodic KYC updation cycle for a low-risk  | n/a | n/a |
| How often must an NBFC carry out re-KYC for high-risk c | n/a | n/a |
| What is the periodic updation interval for medium-risk  | n/a | n/a |
| Which Master Direction governs the issuance and conduct | n/a | n/a |
| What rules apply to an NBFC accepting public deposits? | n/a | n/a |
| Where are the capital adequacy prudential norms for NBF | n/a | n/a |