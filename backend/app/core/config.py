"""Validated, environment-based application configuration."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
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

    @field_validator("app_name", "app_version")
    @classmethod
    def value_must_not_be_blank(cls, value: str) -> str:
        """Reject empty identifying values."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("value must not be blank")
        return normalized

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

    @model_validator(mode="after")
    def validate_security_mode(self) -> Self:
        """Prevent unsafe production debug and accidental local HSTS."""
        if self.environment is Environment.PRODUCTION and self.debug:
            raise ValueError("DEBUG must be false in production")
        if self.enable_hsts and self.environment is not Environment.PRODUCTION:
            raise ValueError("HSTS may only be enabled in production")
        return self

    @property
    def cors_origins(self) -> list[str]:
        """Return the validated CORS origins as a list for Starlette."""
        return self.allowed_origins.split(",")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()
