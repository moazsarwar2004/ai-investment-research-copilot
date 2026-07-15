"""Fail-fast settings validation tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

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
