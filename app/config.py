"""Central, typed configuration.

Every setting is read from environment variables (or a local `.env` file) and
validated by Pydantic. Reading config in ONE place means the rest of the code
never touches os.environ directly, and a missing/malformed value fails loudly at
startup instead of deep inside a request.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # tolerate keys we don't map yet (LLM/embedding come later)
    )

    # Relational DB
    database_url: str = "postgresql://compliance:compliance@localhost:5432/compliancegpt"

    # Vector DB
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "compliance_chunks"

    # Embeddings. Spec's intended model is BAAI/bge-m3 (1024-dim, multilingual),
    # but it needs ~2.2GB disk; the MVP uses the small English model to fit.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_device: str = "cpu"  # cpu | cuda
    embedding_dim: int = 384       # must match embedding_model's output size

    # LLM (answer generation). Swappable per PROJECT_SPEC.md §7 — never hardcoded.
    # Default = Groq (free, hosted, open-source Llama). Any OpenAI-compatible
    # backend works by changing llm_base_url + llm_model (Ollama, OpenRouter, …).
    # Set llm_provider="anthropic" to use Claude instead.
    llm_provider: str = "groq"            # groq | anthropic | openai | ollama | ...
    llm_model: str = "llama-3.3-70b-versatile"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""                 # Groq key (gsk_...) via LLM_API_KEY
    anthropic_api_key: str = ""           # only used when llm_provider="anthropic"
    groundedness_threshold: float = 0.7

    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8000


# Import this singleton everywhere: `from app.config import settings`
settings = Settings()
