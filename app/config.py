"""Central, typed configuration.

Every setting is read from environment variables (or a local `.env` file) and
validated by Pydantic. Reading config in ONE place means the rest of the code
never touches os.environ directly, and a missing/malformed value fails loudly at
startup instead of deep inside a request.
"""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.retrieval.types import RetrievalStrategy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # tolerate keys we don't map yet (LLM/embedding come later)
    )

    # Relational DB
    database_url: str = "postgresql://compliance:compliance@127.0.0.1:5432/compliancegpt"

    # Vector DB
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "compliance_chunks"

    # Embeddings. Default is the small model by MEASUREMENT, not preference: the
    # spec's BGE-M3 (1024-dim, 2.2GB) embedded 0/868 chunks in 33 min on an
    # 7.8GB-RAM box (it swapped to disk); bge-small does all 868 in ~4 min.
    # On >= 16GB RAM, switch BOTH together: BAAI/bge-m3 + embedding_dim=1024.
    # (Qdrant's collection auto-recreates on a dim change — see embed_and_upsert.)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str = "cpu"  # cpu | cuda
    embedding_dim: int = 384  # must match embedding_model's output size

    # Reranker (cross-encoder). Small MiniLM for the same RAM reason; the spec's
    # BAAI/bge-reranker-v2-m3 (~2.2GB) needs a larger machine.
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # LLM (answer generation). Swappable per PROJECT_SPEC.md §7 — never hardcoded.
    # Default = Groq (free, hosted, open-source Llama). Any OpenAI-compatible
    # backend works by changing llm_base_url + llm_model (Ollama, OpenRouter, …).
    # Set llm_provider="anthropic" to use Claude instead.
    llm_provider: str = "groq"  # groq | anthropic | openai | ollama | ...
    llm_model: str = "llama-3.3-70b-versatile"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""  # Groq key (gsk_...) via LLM_API_KEY
    anthropic_api_key: str = ""  # only used when llm_provider="anthropic"
    llm_timeout_seconds: float = Field(30, ge=5, le=300)
    llm_max_retries: int = Field(0, ge=0, le=5)
    groundedness_threshold: float = 0.7

    # Cost-aware routing: small, structured tasks (scope classification) go to a
    # cheaper model; only answer generation needs the large one. On Groq the two
    # models also draw on SEPARATE daily token quotas, so routing buys headroom
    # as well as cost. Set llm_model_fast = llm_model to disable routing.
    llm_model_fast: str = "llama-3.1-8b-instant"

    # Observability — Langfuse tracing is OPTIONAL. With both keys unset, the
    # agent still records per-node latency in-process (app/observability/tracing.py);
    # setting them additionally exports each trace to Langfuse.
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # Retrieval: vector routes remain available through the vector extra.
    retrieval_strategy: RetrievalStrategy = "dense"
    evidence_storage_path: str = "data/evidence"
    pageindex_storage_path: str = "data/pageindex"
    pageindex_tree_mode: Literal["full", "layout"] = "full"
    pageindex_navigation_mode: Literal["local", "llm"] = "local"
    pageindex_index_model: str = ""  # empty uses llm_model_fast
    pageindex_min_interval_seconds: float = Field(20, ge=0, le=300)
    pageindex_max_output_tokens: int = Field(4096, ge=512, le=16384)
    pageindex_max_attempts: int = Field(4, ge=1, le=8)
    pageindex_max_retry_wait_seconds: float = Field(120, ge=1, le=600)
    retrieval_max_documents: int = Field(5, ge=1, le=20)
    retrieval_navigation_documents: int = Field(1, ge=1, le=5)
    retrieval_max_pages: int = Field(8, ge=1, le=40)
    retrieval_max_rounds: int = Field(3, ge=1, le=6)
    retrieval_max_context_chars: int = Field(24000, ge=1, le=100000)
    cache_ttl_seconds: int = Field(300, ge=1, le=3600)
    compliancegpt_api: str = "http://localhost:8000"

    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_key: str = ""  # if set, /api/query requires header X-API-Key
    rate_limit_per_min: int = 30  # per-client requests/min on /api/query


# Import this singleton everywhere: `from app.config import settings`
settings = Settings()
