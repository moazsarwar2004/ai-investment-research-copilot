"""Password, opaque-token, and signed access-token security primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from backend.app.core.config import Settings
from backend.app.core.exceptions import AuthenticationError

_ISSUER = "ai-investment-research-copilot"
_AUDIENCE = "copilot-api"


@lru_cache(maxsize=8)
def _password_context(
    time_cost: int, memory_cost: int, parallelism: int
) -> tuple[PasswordHasher, str]:
    """Build and reuse a tunable Argon2id context and timing-safe dummy hash."""
    password_hasher = PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    return password_hasher, password_hasher.hash("constant-time-login-placeholder")


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Validated claims trusted by authorization dependencies."""

    user_id: UUID
    session_id: UUID
    role: str
    authenticated_at: datetime
    expires_at: datetime


class IdentitySecurity:
    """Centralize tunable password hashing and token cryptography."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._password_hasher, self._dummy_password_hash = _password_context(
            settings.argon2_time_cost,
            settings.argon2_memory_cost_kib,
            settings.argon2_parallelism,
        )

    def hash_password(self, password: str) -> str:
        """Hash a validated password with Argon2id."""
        return self._password_hasher.hash(password)

    def verify_password(self, password_hash: str | None, password: str) -> bool:
        """Verify without revealing whether an email exists through fast failure."""
        candidate_hash = password_hash or self._dummy_password_hash
        try:
            valid = self._password_hasher.verify(candidate_hash, password)
        except (InvalidHashError, VerificationError):
            return False
        return bool(valid and password_hash is not None)

    def password_needs_rehash(self, password_hash: str) -> bool:
        """Report when current Argon2id policy should replace an older hash."""
        return self._password_hasher.check_needs_rehash(password_hash)

    @staticmethod
    def new_opaque_token() -> str:
        """Create a high-entropy URL-safe one-time token."""
        return secrets.token_urlsafe(48)

    def digest_token(self, token: str) -> str:
        """Create a keyed digest so a database leak cannot recover raw tokens."""
        return hmac.new(
            self._settings.digest_key.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def digest_client_value(self, value: str | None) -> str | None:
        """Pseudonymize IP/client values before durable audit storage."""
        normalized = (value or "").strip()
        if not normalized:
            return None
        return self.digest_token(f"client:{normalized}")

    def create_access_token(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        role: str,
        authenticated_at: datetime,
        now: datetime,
    ) -> tuple[str, datetime]:
        """Mint one short-lived bearer token with explicit type and audience."""
        issued_at = now.astimezone(UTC)
        expires_at = issued_at + timedelta(
            minutes=self._settings.access_token_ttl_minutes
        )
        payload: dict[str, Any] = {
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "sub": str(user_id),
            "sid": str(session_id),
            "role": role,
            "type": "access",
            "jti": str(uuid4()),
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
            "auth_time": int(authenticated_at.astimezone(UTC).timestamp()),
        }
        encoded = jwt.encode(payload, self._settings.jwt_key, algorithm="HS256")
        return encoded, expires_at

    def decode_access_token(self, token: str) -> AccessTokenClaims:
        """Fully validate a bearer token before converting claims to typed values."""
        try:
            payload = jwt.decode(
                token,
                self._settings.jwt_key,
                algorithms=["HS256"],
                audience=_AUDIENCE,
                issuer=_ISSUER,
                options={
                    "require": [
                        "exp",
                        "iat",
                        "nbf",
                        "sub",
                        "sid",
                        "jti",
                        "type",
                        "auth_time",
                    ]
                },
            )
            if payload.get("type") != "access":
                raise ValueError("unexpected token type")
            role = payload.get("role")
            expires_at = payload.get("exp")
            authenticated_at = payload.get("auth_time")
            if (
                not isinstance(role, str)
                or not isinstance(expires_at, int | float)
                or not isinstance(authenticated_at, int | float)
            ):
                raise ValueError("invalid token claims")
            return AccessTokenClaims(
                user_id=UUID(str(payload["sub"])),
                session_id=UUID(str(payload["sid"])),
                role=role,
                authenticated_at=datetime.fromtimestamp(authenticated_at, tz=UTC),
                expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as error:
            raise AuthenticationError(
                "The access token is invalid or expired."
            ) from error
