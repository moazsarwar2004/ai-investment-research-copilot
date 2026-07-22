"""Thin Phase 3 HTTP routes for authentication, accounts, and administration."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from backend.app.api.dependencies import (
    get_admin_principal,
    get_auth_rate_limiter,
    get_current_principal,
    get_identity_service,
    get_request_context,
)
from backend.app.core.rate_limits import AuthRateLimiter
from backend.app.schemas.identity import (
    AdminUserUpdateRequest,
    AuditResponse,
    EmailRequest,
    LoginRequest,
    MessageResponse,
    PasswordResetConfirmRequest,
    RefreshRequest,
    RegisterRequest,
    SessionResponse,
    TokenPairResponse,
    TokenRequest,
    UpdateProfileRequest,
    UserResponse,
)
from backend.app.services import (
    CurrentPrincipal,
    IdentityService,
    RequestContext,
    TokenPair,
)

identity_router = APIRouter()
ContextDependency = Annotated[RequestContext, Depends(get_request_context)]
ServiceDependency = Annotated[IdentityService, Depends(get_identity_service)]
LimiterDependency = Annotated[AuthRateLimiter, Depends(get_auth_rate_limiter)]
PrincipalDependency = Annotated[CurrentPrincipal, Depends(get_current_principal)]
AdminDependency = Annotated[CurrentPrincipal, Depends(get_admin_principal)]
LimitQuery = Annotated[int, Query(ge=1, le=100)]
OffsetQuery = Annotated[int, Query(ge=0)]


def _disable_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _token_response(pair: TokenPair) -> TokenPairResponse:
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        access_expires_at=pair.access_expires_at,
        refresh_expires_at=pair.refresh_expires_at,
        user=UserResponse.model_validate(pair.user),
    )


async def _limit(
    *,
    operation: str,
    identity: str,
    context: RequestContext,
    service: IdentityService,
    limiter: AuthRateLimiter,
) -> None:
    material = f"{operation}:{context.client_ip or 'unknown'}:{identity}"
    await limiter.check(service.security.digest_token(material))


@identity_router.post(
    "/auth/register",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["authentication"],
)
async def register(
    payload: RegisterRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> MessageResponse:
    """Create an unverified account under the strict auth-attempt limit."""
    _disable_caching(response)
    await _limit(
        operation="register",
        identity=payload.email,
        context=context,
        service=service,
        limiter=limiter,
    )
    _, token = await service.register(
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
        context=context,
    )
    return MessageResponse(
        message="Registration accepted. Verify the email before login.",
        test_token=token,
    )


@identity_router.post(
    "/auth/verify-email",
    response_model=UserResponse,
    tags=["authentication"],
)
async def verify_email(
    payload: TokenRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> UserResponse:
    """Consume one verification token and activate its account."""
    _disable_caching(response)
    await _limit(
        operation="verify",
        identity=payload.token,
        context=context,
        service=service,
        limiter=limiter,
    )
    user = await service.verify_email(token=payload.token, context=context)
    return UserResponse.model_validate(user)


@identity_router.post(
    "/auth/verification/resend",
    response_model=MessageResponse,
    tags=["authentication"],
)
async def resend_verification(
    payload: EmailRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> MessageResponse:
    """Return the same result whether or not the email is eligible."""
    _disable_caching(response)
    await _limit(
        operation="verify-resend",
        identity=payload.email,
        context=context,
        service=service,
        limiter=limiter,
    )
    token = await service.resend_verification(email=payload.email, context=context)
    return MessageResponse(
        message="If the account is eligible, verification instructions were issued.",
        test_token=token,
    )


@identity_router.post(
    "/auth/login", response_model=TokenPairResponse, tags=["authentication"]
)
async def login(
    payload: LoginRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> TokenPairResponse:
    """Verify credentials and issue a short access/rotating refresh pair."""
    _disable_caching(response)
    await _limit(
        operation="login",
        identity=payload.email,
        context=context,
        service=service,
        limiter=limiter,
    )
    return _token_response(
        await service.login(
            email=payload.email,
            password=payload.password,
            context=context,
        )
    )


@identity_router.post(
    "/auth/refresh", response_model=TokenPairResponse, tags=["authentication"]
)
async def refresh(
    payload: RefreshRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> TokenPairResponse:
    """Rotate one refresh token and revoke its family on replay."""
    _disable_caching(response)
    await _limit(
        operation="refresh",
        identity=payload.refresh_token,
        context=context,
        service=service,
        limiter=limiter,
    )
    return _token_response(
        await service.refresh(
            refresh_token=payload.refresh_token,
            context=context,
        )
    )


@identity_router.post(
    "/auth/logout", response_model=MessageResponse, tags=["authentication"]
)
async def logout(
    payload: RefreshRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
) -> MessageResponse:
    """Idempotently revoke the supplied refresh-token family."""
    _disable_caching(response)
    await service.logout(refresh_token=payload.refresh_token, context=context)
    return MessageResponse(message="The session has been logged out.")


@identity_router.post(
    "/auth/logout-all", response_model=MessageResponse, tags=["authentication"]
)
async def logout_all(
    response: Response,
    context: ContextDependency,
    principal: PrincipalDependency,
    service: ServiceDependency,
) -> MessageResponse:
    """Revoke every session owned by the current account."""
    _disable_caching(response)
    count = await service.logout_all(principal=principal, context=context)
    return MessageResponse(message=f"Revoked {count} active session(s).")


@identity_router.post(
    "/auth/password-reset/request",
    response_model=MessageResponse,
    tags=["authentication"],
)
async def request_password_reset(
    payload: EmailRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> MessageResponse:
    """Issue reset material without revealing account existence."""
    _disable_caching(response)
    await _limit(
        operation="password-reset-request",
        identity=payload.email,
        context=context,
        service=service,
        limiter=limiter,
    )
    token = await service.request_password_reset(email=payload.email, context=context)
    return MessageResponse(
        message="If the account is eligible, password reset instructions were issued.",
        test_token=token,
    )


@identity_router.post(
    "/auth/password-reset/confirm",
    response_model=MessageResponse,
    tags=["authentication"],
)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    response: Response,
    context: ContextDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> MessageResponse:
    """Consume a reset token and revoke all existing sessions."""
    _disable_caching(response)
    await _limit(
        operation="password-reset-confirm",
        identity=payload.token,
        context=context,
        service=service,
        limiter=limiter,
    )
    await service.confirm_password_reset(
        token=payload.token,
        new_password=payload.new_password,
        context=context,
    )
    return MessageResponse(
        message="The password was changed; all sessions were revoked."
    )


@identity_router.get("/users/me", response_model=UserResponse, tags=["accounts"])
async def current_user(
    response: Response,
    principal: PrincipalDependency,
) -> UserResponse:
    """Return the current database-backed profile and role."""
    _disable_caching(response)
    return UserResponse.model_validate(principal.user)


@identity_router.patch("/users/me", response_model=UserResponse, tags=["accounts"])
async def update_current_user(
    payload: UpdateProfileRequest,
    response: Response,
    context: ContextDependency,
    principal: PrincipalDependency,
    service: ServiceDependency,
) -> UserResponse:
    """Update only owner-editable profile fields."""
    _disable_caching(response)
    user = await service.update_profile(
        principal=principal,
        display_name=payload.display_name,
        context=context,
    )
    return UserResponse.model_validate(user)


@identity_router.get(
    "/users/me/sessions", response_model=list[SessionResponse], tags=["accounts"]
)
async def list_sessions(
    response: Response,
    principal: PrincipalDependency,
    service: ServiceDependency,
) -> list[SessionResponse]:
    """List sanitized active sessions for the current owner."""
    _disable_caching(response)
    sessions = await service.list_sessions(principal=principal)
    return [
        SessionResponse(
            id=item.id,
            current=item.id == principal.session.id,
            created_at=item.created_at,
            last_used_at=item.last_used_at,
            expires_at=item.expires_at,
            user_agent=item.user_agent,
        )
        for item in sessions
    ]


@identity_router.delete(
    "/users/me/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["accounts"],
)
async def revoke_session(
    session_id: UUID,
    context: ContextDependency,
    principal: PrincipalDependency,
    service: ServiceDependency,
) -> Response:
    """Revoke an owned session; cross-user IDs remain indistinguishable from missing."""
    await service.revoke_owned_session(
        principal=principal,
        session_id=session_id,
        context=context,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@identity_router.get(
    "/admin/users", response_model=list[UserResponse], tags=["administration"]
)
async def admin_list_users(
    response: Response,
    principal: AdminDependency,
    service: ServiceDependency,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> list[UserResponse]:
    """Return a bounded user catalog to administrators."""
    _disable_caching(response)
    users = await service.admin_list_users(
        principal=principal, limit=limit, offset=offset
    )
    return [UserResponse.model_validate(user) for user in users]


@identity_router.patch(
    "/admin/users/{user_id}",
    response_model=UserResponse,
    tags=["administration"],
)
async def admin_update_user(
    user_id: UUID,
    payload: AdminUserUpdateRequest,
    response: Response,
    context: ContextDependency,
    principal: AdminDependency,
    service: ServiceDependency,
    limiter: LimiterDependency,
) -> UserResponse:
    """Apply a fresh-auth, rate-limited, audited role/status change."""
    _disable_caching(response)
    await _limit(
        operation="admin-user-update",
        identity=str(principal.user.id),
        context=context,
        service=service,
        limiter=limiter,
    )
    user = await service.admin_update_user(
        principal=principal,
        target_user_id=user_id,
        role=payload.role,
        status=payload.status,
        context=context,
    )
    return UserResponse.model_validate(user)


@identity_router.get(
    "/admin/audit-logs",
    response_model=list[AuditResponse],
    tags=["administration"],
)
async def admin_list_audits(
    response: Response,
    principal: AdminDependency,
    service: ServiceDependency,
    limit: LimitQuery = 50,
    offset: OffsetQuery = 0,
) -> list[AuditResponse]:
    """Return append-only audit evidence to administrators."""
    _disable_caching(response)
    audits = await service.admin_list_audits(
        principal=principal, limit=limit, offset=offset
    )
    return [AuditResponse.model_validate(item) for item in audits]
