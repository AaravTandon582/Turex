"""Application configuration, loaded from the environment.

Every value that differs between a laptop, CI, and production lives here. Nothing in the
codebase reads ``os.environ`` directly.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Environment(StrEnum):
    local = "local"
    test = "test"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    environment: Environment = Environment.local
    debug: bool = False

    # --- HTTP -----------------------------------------------------------------
    api_prefix: str = "/api/v1"
    # NoDecode: accept a plain comma-separated string in the environment rather than
    # requiring JSON, which is what people actually write in a .env file.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Database -------------------------------------------------------------
    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://localhost/atlas"),
        description="SQLAlchemy async DSN. Must use the asyncpg driver.",
    )
    database_pool_size: int = 10
    database_max_overflow: int = 5
    database_echo: bool = False

    # --- Security -------------------------------------------------------------
    secret_key: str = Field(
        default="dev-only-insecure-key-change-me",
        min_length=16,
        description="Signs access tokens. Must be a strong random value outside local dev.",
    )
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 60 * 60
    cookie_domain: str | None = None
    cookie_secure: bool = False
    """Set True in production so session cookies are only sent over HTTPS."""

    # --- Storage --------------------------------------------------------------
    storage_root: Path = Path("var/storage")
    max_upload_bytes: int = 50 * 1024 * 1024

    # --- AI providers ---------------------------------------------------------
    chat_provider: str = "anthropic"
    embedding_provider: str = "openai"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    embedding_dimensions: int = 1536
    """Fixed at the pgvector column level. Changing it requires a re-index migration."""

    # --- Ingestion ------------------------------------------------------------
    worker_enabled: bool = True
    worker_poll_seconds: float = 2.0
    worker_concurrency: int = 2
    job_max_attempts: int = 3

    @field_validator("database_url")
    @classmethod
    def _require_async_driver(cls, value: PostgresDsn) -> PostgresDsn:
        if "+asyncpg" not in str(value):
            raise ValueError("database_url must use the postgresql+asyncpg:// scheme")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.production

    def check_production_readiness(self) -> list[str]:
        """Return configuration problems that must not ship to production.

        Called at startup rather than import time so tests and local runs stay unaffected.
        """
        problems: list[str] = []
        if self.secret_key == "dev-only-insecure-key-change-me":
            problems.append("SECRET_KEY is still the development default")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true so session cookies require HTTPS")
        if self.debug:
            problems.append("DEBUG must be false")
        return problems


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
