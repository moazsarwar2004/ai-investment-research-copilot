"""Unversioned probes and versioned application health routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.core.config import Settings
from backend.app.core.exceptions import ServiceUnavailableError

root_router = APIRouter(tags=["application"])
probe_router = APIRouter(tags=["health"])
health_router = APIRouter(tags=["health"])


class StrictResponseModel(BaseModel):
    """Base response model that rejects accidental undocumented fields."""

    model_config = ConfigDict(extra="forbid")


class RootResponse(StrictResponseModel):
    """Public service-discovery response."""

    service: str
    version: str
    environment: str
    documentation: str | None
    health: str


class LivenessResponse(StrictResponseModel):
    """Process liveness response."""

    status: Literal["alive"]
    service: str
    version: str


class ReadinessChecks(StrictResponseModel):
    """Phase 1 readiness checks."""

    application: Literal["ok"]
    configuration: Literal["ok"]


class ReadinessResponse(StrictResponseModel):
    """Application readiness response."""

    status: Literal["ready"]
    checks: ReadinessChecks


class VersionedHealthResponse(StrictResponseModel):
    """Versioned health and environment metadata."""

    service: str
    version: str
    environment: str
    status: Literal["healthy"]
    timestamp: datetime


def _settings(request: Request) -> Settings:
    settings: object = request.app.state.settings
    if not isinstance(settings, Settings):
        raise ServiceUnavailableError("Application configuration is unavailable.")
    return settings


def _disable_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@root_router.get("/", response_model=RootResponse)
async def application_information(request: Request, response: Response) -> RootResponse:
    """Return non-sensitive service metadata and navigation paths."""
    _disable_caching(response)
    settings = _settings(request)
    return RootResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
        documentation="/docs" if settings.docs_enabled else None,
        health=f"{settings.api_v1_prefix}/health",
    )


@probe_router.get("/livez", response_model=LivenessResponse)
async def liveness(request: Request, response: Response) -> LivenessResponse:
    """Confirm only that the application process can answer HTTP requests."""
    _disable_caching(response)
    settings = _settings(request)
    return LivenessResponse(
        status="alive",
        service=settings.app_name,
        version=settings.app_version,
    )


@probe_router.get("/readyz", response_model=ReadinessResponse)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    """Confirm startup completion and validated Phase 1 configuration."""
    _disable_caching(response)
    if not getattr(request.app.state, "started", False):
        raise ServiceUnavailableError("Application startup has not completed.")
    _settings(request)
    return ReadinessResponse(
        status="ready",
        checks=ReadinessChecks(application="ok", configuration="ok"),
    )


@health_router.get("/health", response_model=VersionedHealthResponse)
async def versioned_health(
    request: Request, response: Response
) -> VersionedHealthResponse:
    """Return stable, versioned health metadata with a UTC timestamp."""
    _disable_caching(response)
    settings = _settings(request)
    return VersionedHealthResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment.value,
        status="healthy",
        timestamp=datetime.now(UTC),
    )
