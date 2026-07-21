"""Unversioned probes and versioned application health routes."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict

from backend.app.core.config import Settings
from backend.app.core.exceptions import ServiceUnavailableError
from backend.app.core.logger import get_logger
from backend.app.core.resources import ApplicationResources, HealthResource

logger = get_logger(__name__)

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
    """Reduced dependency detail suitable for the public readiness probe."""

    application: Literal["ok"]
    configuration: Literal["ok"]
    database: Literal["ok", "error"]
    redis: Literal["ok", "degraded"]


class ReadinessResponse(StrictResponseModel):
    """Application readiness response."""

    status: Literal["ready", "not_ready"]
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


def _resources(request: Request) -> ApplicationResources:
    resources = getattr(request.app.state, "resources", None)
    if not isinstance(resources, ApplicationResources):
        raise ServiceUnavailableError("Application infrastructure is unavailable.")
    return resources


async def _safe_ping(resource: HealthResource, *, dependency: str) -> bool:
    try:
        return await resource.ping()
    except Exception as error:
        logger.warning(
            "dependency_probe_failed",
            extra={
                "dependency": dependency,
                "exception_type": type(error).__name__,
            },
        )
        return False


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
    """Require PostgreSQL while allowing safe operation without cache acceleration."""
    _disable_caching(response)
    if not getattr(request.app.state, "started", False):
        raise ServiceUnavailableError("Application startup has not completed.")
    _settings(request)
    resources = _resources(request)
    database_ok, redis_ok = await asyncio.gather(
        _safe_ping(resources.database, dependency="database"),
        _safe_ping(resources.cache, dependency="redis"),
    )
    if not database_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if database_ok else "not_ready",
        checks=ReadinessChecks(
            application="ok",
            configuration="ok",
            database="ok" if database_ok else "error",
            redis="ok" if redis_ok else "degraded",
        ),
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
