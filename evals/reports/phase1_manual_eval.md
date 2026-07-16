# Phase 1 — Manual Eval Report

- Date: 2026-07-16
- Strategy: dense-only retrieval (bge-small-en-v1.5, 384-dim) + Groq llama-3.3-70b generation
- Golden set: 30 rows (26 answerable)

## Retrieval metrics (answerable rows)

- **Recall@5: 92.3%**  (expected doc appears in top 5)
- **MRR: 0.811**

| Question | Expected | Rank | Top-1 |
|---|---|---|---|
| What is the periodic KYC updation cycle for a low-risk indiv | RBI/DOR/2025-26/361 | 1 | RBI/DOR/2025-26/361 |
| How often must an NBFC carry out re-KYC for high-risk custom | RBI/DOR/2025-26/361 | 1 | RBI/DOR/2025-26/361 |
| What is the periodic updation interval for medium-risk NBFC  | RBI/DOR/2025-26/361 | 1 | RBI/DOR/2025-26/361 |
| Which Master Direction governs the issuance and conduct of c | RBI/DOR/2025-26/348 | 1 | RBI/DOR/2025-26/348 |
| What rules apply to an NBFC accepting public deposits? | RBI/DOR/2025-26/346 | 1 | RBI/DOR/2025-26/346 |
| Where are the capital adequacy prudential norms for NBFCs sp | RBI/DOR/2025-26/345 | MISS | RBI/DOR/2025-26/371 |
| What governs the declaration of dividends by an NBFC? | RBI/DOR/2025-26/360 | 1 | RBI/DOR/2025-26/360 |
| Which direction covers microfinance loans provided by NBFCs? | RBI/DOR/2025-26/371 | 2 | RBI/DOR/2025-26/347 |
| What framework applies to a peer-to-peer lending platform in | RBI/DOR/2025-26/370 | 1 | RBI/DOR/2025-26/370 |
| How are NBFCs classified under scale-based regulation? | RBI/DOR/2025-26/339 | 1 | RBI/DOR/2025-26/339 |
| What are the income recognition and asset classification nor | RBI/DOR/2025-26/356 | 4 | RBI/DOR/2025-26/357 |
| Which direction governs resolution of stressed assets for NB | RBI/DOR/2025-26/357 | 1 | RBI/DOR/2025-26/357 |
| How does the RBI treat wilful defaulters and large defaulter | RBI/DOR/2025-26/358 | 1 | RBI/DOR/2025-26/358 |
| What are the requirements for an NBFC outsourcing arrangemen | RBI/DOR/2025-26/363 | 1 | RBI/DOR/2025-26/363 |
| Which direction covers climate change risk management for NB | RBI/DOR/2025-26/364 | 1 | RBI/DOR/2025-26/364 |
| What governance framework applies to NBFC boards? | RBI/DOR/2025-26/344 | 2 | RBI/DoR/2025-26/368 |
| What are the rules for an NBFC acquiring shareholding or con | RBI/DOR/2025-26/340 | 1 | RBI/DOR/2025-26/340 |
| Which direction governs securitisation transactions undertak | RBI/DOR/2025-26/353 | 1 | RBI/DOR/2025-26/353 |
| What norms cover asset-liability management for NBFCs? | RBI/DoR/2025-26/355 | 1 | RBI/DoR/2025-26/355 |
| What applies to an NBFC operating as an Account Aggregator? | RBI/DoR/2025-26/368 | 1 | RBI/DoR/2025-26/368 |
| Does an NBFC need authorisation to open a new branch? | RBI/DOR/2025-26/342 | 1 | RBI/DOR/2025-26/342 |
| What are the credit information reporting obligations of an  | RBI/DOR/2025-26/349 | MISS | RBI/DOR/2025-26/347 |
| Which direction governs concentration risk (large exposures) | RBI/DOR/2025-26/351 | 1 | RBI/DOR/2025-26/351 |
| What responsible business conduct requirements apply to NBFC | RBI/DOR/2025-26/362 | 2 | RBI/DOR/2025-26/347 |
| How must an NBFC present its financial statements and disclo | RBI/DOR/2025-26/359 | 3 | RBI/DOR/2025-26/353 |
| Can two NBFCs voluntarily amalgamate, and what governs it? | RBI/DoR/2025-26/341 | 1 | RBI/DoR/2025-26/341 |

## End-to-end generation sample

### ✅ What is the periodic KYC updation cycle for a low-risk individual customer at an NBFC?
- expected: ['RBI/DOR/2025-26/361'] · cited: ['RBI/DOR/2025-26/361']
- answer: According to [RBI/DOR/2025-26/361], the periodic KYC updation cycle for a low-risk individual customer at an NBFC is once in every 10 years from the date of opening of the account / last KYC updation. However, it is also mentioned in [RBI/DOR/2025-26/361] that notwithstanding the provisions given above, in respect of an individual customer who is categorised as low-risk, the NBFC shall allow all t

### ✅ How often must an NBFC carry out re-KYC for high-risk customers?
- expected: ['RBI/DOR/2025-26/361'] · cited: ['RBI/DOR/2025-26/361']
- answer: According to [RBI/DOR/2025-26/361], an NBFC shall carry out periodic updation of KYC at least once in every two years for high-risk customers. 

This is decision-support information, not legal advice.

### ✅ What is the periodic updation interval for medium-risk NBFC customers?
- expected: ['RBI/DOR/2025-26/361'] · cited: ['RBI/DOR/2025-26/361']
- answer: According to [RBI/DOR/2025-26/361], the periodic updation interval for medium-risk NBFC customers is once in every eight years from the date of opening of the account / last KYC updation.

This is decision-support information, not legal advice.

### ✅ Which Master Direction governs the issuance and conduct of credit cards by NBFCs?
- expected: ['RBI/DOR/2025-26/348'] · cited: ['RBI/DOR/2025-26/348']
- answer: The Master Direction that governs the issuance and conduct of credit cards by NBFCs is the Reserve Bank of India (Non-Banking Financial Companies - Credit Cards: Issuance and Conduct) Directions, 2025 [RBI/DOR/2025-26/348]. 

This is decision-support information, not legal advice.

### ✅ What is the GST filing deadline for a partnership firm?
- expected: (none — refusal expected) · cited: (none)
- answer: The provided reference context does not contain information about the GST filing deadline for a partnership firm [No relevant source document]. 

This is decision-support information, not legal advice.

### ✅ Who won the 2024 cricket world cup?
- expected: (none — refusal expected) · cited: (none)
- answer: The provided reference context does not contain any information about the 2024 cricket world cup. 

This is decision-support information, not legal advice.
