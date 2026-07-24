"""Validated, environment-based application configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from backend import __version__


class Environment(StrEnum):
    """Supported deployment environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    """Supported application log renderers."""

    JSON = "json"
    CONSOLE = "console"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        validate_default=True,
    )

    app_name: str = "AI Investment Research Co-Pilot"
    app_version: str = __version__
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: LogFormat = LogFormat.JSON
    allowed_origins: str = "http://localhost:8501"
    docs_enabled: bool = True
    enable_hsts: bool = False
    hsts_max_age_seconds: int = Field(default=31_536_000, ge=0)

    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://copilot_app:local-app-only@127.0.0.1:5432/copilot"
    )
    migration_database_url: SecretStr | None = None
    database_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    database_command_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    database_probe_timeout_seconds: float = Field(default=3.0, gt=0, le=10)
    database_pool_size: int = Field(default=5, ge=1, le=20)
    database_max_overflow: int = Field(default=5, ge=0, le=20)
    database_pool_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    database_pool_recycle_seconds: int = Field(default=1_800, ge=60, le=86_400)

    redis_url: SecretStr = SecretStr("redis://127.0.0.1:6379/0")
    redis_key_prefix: str = "copilot:v1"
    redis_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    redis_socket_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    redis_health_check_interval_seconds: int = Field(default=30, ge=1, le=300)

    provider_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    provider_read_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    provider_write_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    provider_pool_timeout_seconds: float = Field(default=1.0, gt=0, le=10)
    provider_total_deadline_seconds: float = Field(default=5.0, gt=0, le=60)
    provider_max_attempts: int = Field(default=3, ge=1, le=5)
    provider_retry_base_seconds: float = Field(default=0.1, ge=0, le=5)
    provider_retry_max_seconds: float = Field(default=1.0, ge=0, le=10)
    provider_retry_after_max_seconds: float = Field(default=30.0, gt=0, le=300)
    provider_response_max_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=20 * 1024 * 1024,
    )
    provider_circuit_failure_threshold: int = Field(default=3, ge=1, le=20)
    provider_circuit_recovery_seconds: float = Field(default=30.0, gt=0, le=600)
    provider_cache_lock_ttl_seconds: int = Field(default=10, ge=1, le=60)
    provider_cache_lock_wait_seconds: float = Field(default=1.0, ge=0, le=10)
    provider_cache_lock_poll_seconds: float = Field(default=0.05, gt=0, le=1)

    jwt_signing_key: SecretStr = SecretStr(
        "local-jwt-signing-key-change-before-sharing-32-bytes"
    )
    token_digest_key: SecretStr = SecretStr(
        "local-token-digest-key-change-before-sharing-32-bytes"
    )
    access_token_ttl_minutes: int = Field(default=15, ge=5, le=60)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=30)
    refresh_family_ttl_days: int = Field(default=30, ge=1, le=90)
    email_verification_ttl_hours: int = Field(default=24, ge=1, le=168)
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=120)
    fresh_auth_ttl_minutes: int = Field(default=15, ge=5, le=60)
    auth_rate_limit_attempts: int = Field(default=5, ge=1, le=100)
    auth_rate_limit_window_seconds: int = Field(default=900, ge=60, le=86_400)
    auth_expose_test_tokens: bool = False
    argon2_time_cost: int = Field(default=3, ge=1, le=10)
    argon2_memory_cost_kib: int = Field(default=65_536, ge=8_192, le=262_144)
    argon2_parallelism: int = Field(default=4, ge=1, le=16)

    @field_validator("app_name", "app_version")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        """Reject empty identifying values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

    @field_validator("jwt_signing_key", "token_digest_key")
    @classmethod
    def validate_identity_secret(cls, value: SecretStr) -> SecretStr:
        """Require enough entropy capacity for signing and keyed token digests."""
        if len(value.get_secret_value()) < 32:
            raise ValueError("identity secrets must contain at least 32 characters")
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        """Require a simple absolute API path without a trailing slash."""
        normalized = value.strip()
        if (
            not normalized.startswith("/")
            or normalized == "/"
            or normalized.endswith("/")
            or ".." in normalized
        ):
            raise ValueError(
                "API_V1_PREFIX must be an absolute path without a trailing slash"
            )
        allowed = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/_-"
        )
        if any(character not in allowed for character in normalized):
            raise ValueError("API_V1_PREFIX contains unsupported characters")
        return normalized

    @field_validator("allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, value: str) -> str:
        """Validate and normalize a comma-separated CORS origin allowlist."""
        normalized_origins: list[str] = []
        for candidate in value.split(","):
            origin = candidate.strip()
            if not origin:
                continue
            if origin == "*":
                raise ValueError("wildcard CORS origins are not allowed")

            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"invalid CORS origin: {origin}")
            if (
                parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    f"CORS origin must not contain credentials or a path: {origin}"
                )
            try:
                _ = parsed.port
            except ValueError as error:
                raise ValueError(f"invalid CORS origin port: {origin}") from error

            canonical = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            if canonical not in normalized_origins:
                normalized_origins.append(canonical)

        if not normalized_origins:
            raise ValueError("at least one CORS origin is required")
        return ",".join(normalized_origins)

    @field_validator("database_url", "migration_database_url", mode="before")
    @classmethod
    def validate_database_url(cls, value: object) -> object:
        """Require an async PostgreSQL URL with an explicit database name."""
        if value is None:
            return None
        rendered = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(rendered, str):
            raise ValueError("database URL must be a string")
        parsed = urlsplit(rendered)
        if parsed.scheme != "postgresql+asyncpg":
            raise ValueError("database URL must use postgresql+asyncpg")
        if not parsed.hostname or parsed.path in {"", "/"}:
            raise ValueError("database URL must include a host and database name")
        if parsed.fragment:
            raise ValueError("database URL must not contain a fragment")
        return rendered

    @field_validator("redis_url", mode="before")
    @classmethod
    def validate_redis_url(cls, value: object) -> object:
        """Require a Redis URL whose transport is explicit."""
        rendered = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(rendered, str):
            raise ValueError("Redis URL must be a string")
        parsed = urlsplit(rendered)
        if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
            raise ValueError(
                "REDIS_URL must use redis:// or rediss:// and include a host"
            )
        if parsed.fragment:
            raise ValueError("REDIS_URL must not contain a fragment")
        return rendered

    @field_validator("redis_key_prefix")
    @classmethod
    def validate_redis_key_prefix(cls, value: str) -> str:
        """Keep cache namespaces bounded and operationally recognizable."""
        normalized = value.strip().lower()
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789:_-")
        if not normalized or len(normalized) > 64:
            raise ValueError("REDIS_KEY_PREFIX must contain 1-64 characters")
        if any(character not in allowed for character in normalized):
            raise ValueError("REDIS_KEY_PREFIX contains unsupported characters")
        return normalized

    @model_validator(mode="after")
    def validate_security_mode(self) -> Self:
        """Prevent unsafe production debug and accidental local HSTS."""
        if self.environment is Environment.PRODUCTION and self.debug:
            raise ValueError("DEBUG must be false in production")
        if self.enable_hsts and self.environment is not Environment.PRODUCTION:
            raise ValueError("HSTS may only be enabled in production")
        if self.refresh_family_ttl_days < self.refresh_token_ttl_days:
            raise ValueError(
                "REFRESH_FAMILY_TTL_DAYS must be at least REFRESH_TOKEN_TTL_DAYS"
            )
        if self.jwt_key == self.digest_key:
            raise ValueError("JWT_SIGNING_KEY and TOKEN_DIGEST_KEY must be independent")
        if self.provider_retry_max_seconds < self.provider_retry_base_seconds:
            raise ValueError(
                "PROVIDER_RETRY_MAX_SECONDS must be at least "
                "PROVIDER_RETRY_BASE_SECONDS"
            )
        if self.provider_total_deadline_seconds < max(
            self.provider_connect_timeout_seconds,
            self.provider_read_timeout_seconds,
            self.provider_write_timeout_seconds,
            self.provider_pool_timeout_seconds,
        ):
            raise ValueError(
                "PROVIDER_TOTAL_DEADLINE_SECONDS must cover each provider timeout"
            )
        if self.provider_cache_lock_wait_seconds > self.provider_total_deadline_seconds:
            raise ValueError(
                "PROVIDER_CACHE_LOCK_WAIT_SECONDS must not exceed the provider deadline"
            )
        if self.provider_cache_lock_ttl_seconds < self.provider_total_deadline_seconds:
            raise ValueError(
                "PROVIDER_CACHE_LOCK_TTL_SECONDS must cover the provider deadline"
            )
        if self.environment in {Environment.STAGING, Environment.PRODUCTION}:
            if self.auth_expose_test_tokens:
                raise ValueError(
                    "AUTH_EXPOSE_TEST_TOKENS must be false in staging/production"
                )
            if self.jwt_signing_key.get_secret_value().startswith("local-"):
                raise ValueError("JWT_SIGNING_KEY must be replaced before deployment")
            if self.token_digest_key.get_secret_value().startswith("local-"):
                raise ValueError("TOKEN_DIGEST_KEY must be replaced before deployment")
            if self.argon2_time_cost < 2 or self.argon2_memory_cost_kib < 32_768:
                raise ValueError(
                    "staging/production Argon2id settings are below the safety floor"
                )
        return self

    @property
    def cors_origins(self) -> list[str]:
        """Return the validated CORS origins as a list for Starlette."""
        return self.allowed_origins.split(",")

    @property
    def database_dsn(self) -> str:
        """Return the runtime database URL only at the connection boundary."""
        return self.database_url.get_secret_value()

    @property
    def migration_database_dsn(self) -> str:
        """Return the migration URL, falling back for simple environments."""
        if self.migration_database_url is None:
            return self.database_dsn
        return self.migration_database_url.get_secret_value()

    @property
    def redis_dsn(self) -> str:
        """Return the Redis URL only at the connection boundary."""
        return self.redis_url.get_secret_value()

    @property
    def jwt_key(self) -> str:
        """Return the signing secret only at the token boundary."""
        return self.jwt_signing_key.get_secret_value()

    @property
    def digest_key(self) -> str:
        """Return the token-digest secret only at the hashing boundary."""
        return self.token_digest_key.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()
