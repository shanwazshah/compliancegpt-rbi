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

    # App
    api_host: str = "0.0.0.0"
    api_port: int = 8000


# Import this singleton everywhere: `from app.config import settings`
settings = Settings()
