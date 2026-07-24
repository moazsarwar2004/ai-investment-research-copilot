"""Fail-fast settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from backend.app.core.config import Environment, Settings


def test_settings_parse_and_deduplicate_origins() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.TESTING,
        allowed_origins=(
            "http://localhost:8501/, http://localhost:8501, https://example.com"
        ),
    )

    assert settings.cors_origins == [
        "http://localhost:8501",
        "https://example.com",
    ]


@pytest.mark.parametrize(
    "origin",
    ["*", "example.com", "https://example.com/path", "https://user@example.com"],
)
def test_settings_reject_unsafe_cors_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment=Environment.TESTING,
            allowed_origins=origin,
        )


def test_production_rejects_debug_mode() -> None:
    with pytest.raises(ValidationError, match="DEBUG must be false"):
        Settings(_env_file=None, environment=Environment.PRODUCTION, debug=True)


def test_nonproduction_rejects_hsts() -> None:
    with pytest.raises(ValidationError, match="HSTS may only be enabled"):
        Settings(
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            enable_hsts=True,
        )


def test_invalid_api_prefix_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, api_v1_prefix="api/v1")


def test_invalid_environment_value_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"environment": "invalid"})


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "postgresql://localhost/copilot"),
        ("database_url", "postgresql+asyncpg://localhost"),
        ("migration_database_url", "sqlite+aiosqlite:///local.db"),
        ("redis_url", "http://localhost:6379/0"),
    ],
)
def test_settings_reject_invalid_infrastructure_urls(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({field: value})


def test_infrastructure_urls_are_secret_in_settings_representation() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(
            "postgresql+asyncpg://user:database-secret@localhost/copilot"
        ),
        redis_url=SecretStr("redis://:redis-secret@localhost:6379/0"),
        jwt_signing_key=SecretStr("jwt-signing-secret-that-must-not-appear"),
        token_digest_key=SecretStr("token-digest-secret-that-must-not-appear"),
    )

    rendered = repr(settings)

    assert "database-secret" not in rendered
    assert "redis-secret" not in rendered
    assert "jwt-signing-secret" not in rendered
    assert "token-digest-secret" not in rendered
    assert settings.database_dsn.endswith("@localhost/copilot")


def test_deployment_rejects_local_identity_keys_and_token_exposure() -> None:
    with pytest.raises(ValidationError, match="AUTH_EXPOSE_TEST_TOKENS"):
        Settings(
            _env_file=None,
            environment=Environment.STAGING,
            auth_expose_test_tokens=True,
        )

    with pytest.raises(ValidationError, match="JWT_SIGNING_KEY"):
        Settings(_env_file=None, environment=Environment.STAGING)


def test_deployment_rejects_argon2id_below_safety_floor() -> None:
    with pytest.raises(ValidationError, match="Argon2id"):
        Settings(
            _env_file=None,
            environment=Environment.STAGING,
            jwt_signing_key=SecretStr("staging-jwt-key-with-at-least-32-bytes"),
            token_digest_key=SecretStr("staging-digest-key-with-at-least-32-bytes"),
            argon2_time_cost=1,
            argon2_memory_cost_kib=8_192,
        )


def test_provider_retry_and_deadline_relationships_are_validated() -> None:
    with pytest.raises(ValidationError, match="PROVIDER_RETRY_MAX_SECONDS"):
        Settings(
            _env_file=None,
            provider_retry_base_seconds=2,
            provider_retry_max_seconds=1,
        )

    with pytest.raises(ValidationError, match="PROVIDER_TOTAL_DEADLINE_SECONDS"):
        Settings(
            _env_file=None,
            provider_read_timeout_seconds=6,
            provider_total_deadline_seconds=5,
        )

    with pytest.raises(ValidationError, match="PROVIDER_CACHE_LOCK_WAIT_SECONDS"):
        Settings(
            _env_file=None,
            provider_total_deadline_seconds=5,
            provider_cache_lock_wait_seconds=6,
        )

    with pytest.raises(ValidationError, match="PROVIDER_CACHE_LOCK_TTL_SECONDS"):
        Settings(
            _env_file=None,
            provider_total_deadline_seconds=5,
            provider_cache_lock_ttl_seconds=4,
        )
