"""Shared security-header policy for normal and error responses."""

from backend.app.core.config import Settings


def build_security_headers(settings: Settings) -> dict[str, str]:
    """Build the initial response security headers for the current environment."""
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "X-Frame-Options": "DENY",
    }
    if settings.enable_hsts:
        headers["Strict-Transport-Security"] = (
            f"max-age={settings.hsts_max_age_seconds}; includeSubDomains"
        )
    return headers
