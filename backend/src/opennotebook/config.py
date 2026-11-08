"""Application settings, read from environment variables (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    # Application
    app_env: Literal["development", "production", "test"] = "development"
    app_public_url: str = "http://localhost:8080"
    app_secret_key: str = Field(default="", description="JWT signing key")
    app_encryption_key: str = Field(default="", description="base64 32-byte master key for secrets")
    app_default_language: str = "en"
    log_level: str = "INFO"
    access_token_ttl_s: int = 900
    refresh_token_ttl_s: int = 7 * 24 * 3600

    # Hierarchy
    node_max_depth: int = 16

    # Ingestion
    upload_max_mb: int = 500
    chunk_size_tokens: int = 512
    chunk_overlap_tokens: int = 64
    embed_batch_size: int = 32
    ingestion_max_attempts: int = 5
    # Interactive calls (search, chat) must not wait for slow providers as long as background jobs do
    search_timeout_s: int = 30

    # Grounded chat
    # passages retrieved by hybrid search before rerank / diversification
    chat_candidates: int = 40
    # passages given to the chat model
    chat_context_chunks: int = 10
    # at most this many passages from the same source (diversification)
    chat_max_per_source: int = 4
    # previous messages sent with a question
    chat_history_messages: int = 6
    chat_max_tokens: int = 2048
    # interactive rerank call; on timeout or error the fusion order is kept
    rerank_timeout_s: int = 20
    # time allowed for the chat model to start answering before the next model of the chain is tried
    chat_first_token_timeout_s: int = 60

    # Providers
    provider_timeout_s: int = 60
    ollama_timeout_s: int = 600

    # PostgreSQL
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "opennotebook"
    postgres_user: str = "opennotebook"
    postgres_password: str = ""
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    # Other services
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    # ":memory:" runs Qdrant in-process (tests only)
    qdrant_location: str | None = None
    redis_url: str = "redis://redis:6379/0"
    redis_password: str = ""

    # Object storage
    storage_backend: Literal["s3", "filesystem"] = "s3"
    s3_endpoint: str = "http://seaweedfs:8333"
    s3_bucket: str = "opennotebook"
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    filesystem_root: str = "/data/blobs"

    # Authentication
    auth_mode: Literal["local", "oidc"] = "local"
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url_with_auth(self) -> str:
        if self.redis_password and "@" not in self.redis_url:
            scheme, rest = self.redis_url.split("://", 1)
            return f"{scheme}://:{self.redis_password}@{rest}"
        return self.redis_url

    def validate_for_runtime(self) -> None:
        """Fail fast when mandatory secrets are missing outside tests."""
        missing = [
            name
            for name, value in (
                ("APP_SECRET_KEY", self.app_secret_key),
                ("APP_ENCRYPTION_KEY", self.app_encryption_key),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(f"Missing required settings: {', '.join(missing)} (run `make secrets`)")


@lru_cache
def get_settings() -> Settings:
    return Settings()
