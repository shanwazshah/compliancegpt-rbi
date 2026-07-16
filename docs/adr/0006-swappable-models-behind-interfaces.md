# ADR 0006 — Swappable models behind stable interfaces

- Status: Accepted
- Date: 2026-07-16

## Context

The spec names specific models (BGE-M3 embeddings, bge-reranker-v2-m3, a Claude/
GPT-class LLM) but also insists on **not hardcoding a vendor** (§7). The dev
machine can't fit the large models (BGE-M3 ≈ 2.2GB, reranker ≈ 2.2GB) and the
user wanted zero LLM cost.

## Decision

Route every model through a small, config-driven seam and use fit-on-disk
defaults, with the spec's intended models documented and one setting away:

| Role | MVP default | Intended | Seam |
|---|---|---|---|
| Embeddings | `bge-small-en-v1.5` (384d) | `bge-m3` (1024d) | `app/embeddings.py` |
| Reranker | `ms-marco-MiniLM-L-6-v2` | `bge-reranker-v2-m3` | `app/retrieval/rerank.py` |
| LLM | Groq `llama-3.3-70b` (free) | Claude / any | `app/llm.py` |

## Rationale

- **No vendor lock-in.** Groq, Ollama, OpenRouter, and OpenAI all speak the
  OpenAI-compatible API, so supporting free open-source models was a one-path
  change; `LLM_PROVIDER=anthropic` switches to Claude.
- **Config over code.** Switching a model is an `.env` change
  (`EMBEDDING_MODEL` + `EMBEDDING_DIM`, `RERANKER_MODEL`, `LLM_*`); the Qdrant
  collection auto-recreates on an embedding-dimension change.
- **Runs at $0** on constrained hardware while staying faithful to the spec's
  architecture.

## Consequences

- Reported metrics reflect the small models; larger models are expected to lift
  quality (see ADR 0002).
- Every model choice is reversible without touching call sites.
