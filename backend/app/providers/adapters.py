"""Abstract boundary keeping vendor wire formats out of domain services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, cast

from pydantic import BaseModel, ValidationError

from backend.app.providers.exceptions import ProviderSchemaError
from backend.app.providers.models import (
    NormalizedPayload,
    OutboundRequest,
    ProviderHttpResponse,
    ProviderRequest,
)


class ProviderAdapter[DataT: BaseModel](ABC):
    """Contract implemented by each provider/endpoint family."""

    provider: ClassVar[str]
    schema_version: ClassVar[str]
    terms_review_version: ClassVar[str]
    attribution: ClassVar[str]
    allowed_hosts: ClassVar[frozenset[str]]
    data_model: ClassVar[type[BaseModel]]

    @abstractmethod
    def build_request(self, request: ProviderRequest) -> OutboundRequest:
        """Map a provider-neutral operation to an allowlisted HTTP request."""

    @abstractmethod
    def normalize(
        self,
        response: ProviderHttpResponse,
        request: ProviderRequest,
    ) -> NormalizedPayload[DataT]:
        """Validate and normalize one vendor payload."""

    def validate_cached_data(self, value: object) -> DataT:
        """Revalidate cached normalized data after code/schema changes."""
        try:
            validated = self.data_model.model_validate(value)
        except ValidationError as error:
            raise ProviderSchemaError(
                "Cached normalized provider data no longer matches its schema."
            ) from error
        return cast(DataT, validated)

    def reported_used_weight(self, response: ProviderHttpResponse) -> int | None:
        """Return authoritative usage from provider headers when available."""
        return None
