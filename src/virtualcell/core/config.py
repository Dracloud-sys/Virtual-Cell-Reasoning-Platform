"""Application configuration loaded from the environment.

All settings are optional in v0.1: the default knowledge backend is in-memory and
requires no external services.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings, read from environment variables prefixed ``VCELL_``."""

    model_config = SettingsConfigDict(env_prefix="VCELL_", env_file=".env", extra="ignore")

    # Knowledge base
    knowledge_backend: str = "memory"  # memory | neo4j
    # Optional path to a saved graph JSON; if set, the API loads it at startup
    # instead of the bundled sample dataset.
    graph_path: str | None = None

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "changeme"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"

    # PostgreSQL
    postgres_dsn: str = "postgresql://vcell:vcell@localhost:5432/vcell"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Reasoning LLM (the API key itself is read from the standard ANTHROPIC_API_KEY
    # environment variable by the SDK, never from here).
    llm_model: str = "claude-sonnet-5"

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
