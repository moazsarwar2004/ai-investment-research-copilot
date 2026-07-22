"""Strict Phase 3 identity and authorization API schemas."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class IdentitySchema(BaseModel):
    """Reject accidental request/response fields across identity APIs."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class EmailRequest(IdentitySchema):
    """A normalized email-only request."""

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _EMAIL_PATTERN.fullmatch(normalized):
            raise ValueError("email is invalid")
        return normalized


class RegisterRequest(EmailRequest):
    """Registration credentials with a bounded strong password."""

    password: str = Field(min_length=12, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        character_classes = (
            any(character.islower() for character in value),
            any(character.isupper() for character in value),
            any(character.isdigit() for character in value),
            any(not character.isalnum() for character in value),
        )
        if sum(character_classes) < 3:
            raise ValueError("password must use at least three character classes")
        return value


class LoginRequest(EmailRequest):
    """Email/password login input."""

    password: str = Field(min_length=1, max_length=128)


class TokenRequest(IdentitySchema):
    """A raw one-time token accepted only at its dedicated boundary."""

    token: str = Field(min_length=32, max_length=256)


class RefreshRequest(IdentitySchema):
    """A rotating refresh token request."""

    refresh_token: str = Field(min_length=32, max_length=256)


class PasswordResetConfirmRequest(TokenRequest):
    """One-time reset token and replacement password."""

    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return RegisterRequest.validate_password(value)


class MessageResponse(IdentitySchema):
    """A deliberately minimal mutation acknowledgement."""

    message: str
    test_token: str | None = None


class UserResponse(IdentitySchema):
    """Sanitized account fields safe for the account owner/admin catalog."""

    id: UUID
    email: str
    display_name: str | None
    role: Literal["user", "admin"]
    status: Literal["unverified", "active", "disabled"]
    email_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TokenPairResponse(IdentitySchema):
    """Short access token and one-time rotating refresh token."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    access_expires_at: datetime
    refresh_expires_at: datetime
    user: UserResponse


class UpdateProfileRequest(IdentitySchema):
    """Owner-editable account profile fields."""

    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_field(self) -> Self:
        if "display_name" not in self.model_fields_set:
            raise ValueError("display_name must be supplied")
        return self


class SessionResponse(IdentitySchema):
    """Sanitized session metadata; never includes token material or raw IP."""

    id: UUID
    current: bool
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    user_agent: str | None


class AdminUserUpdateRequest(IdentitySchema):
    """Audited administrative role/status mutation."""

    role: Literal["user", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None

    @model_validator(mode="after")
    def at_least_one_change(self) -> Self:
        if self.role is None and self.status is None:
            raise ValueError("at least one field must be supplied")
        return self


class AuditResponse(IdentitySchema):
    """Sanitized append-only audit entry."""

    public_id: UUID
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    request_id: str | None
    details: dict[str, object]
    created_at: datetime
