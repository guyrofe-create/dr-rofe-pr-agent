"""Shared Google OAuth refresh with safe, actionable failure detail."""
from __future__ import annotations

import requests

from . import common


TOKEN_URL = "https://oauth2.googleapis.com/token"


class GoogleOAuthError(RuntimeError):
    """The shared Google refresh credential cannot issue an access token."""


def refresh_access_token(*, session=requests) -> str:
    missing = common.missing_secrets(
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    )
    if missing:
        raise GoogleOAuthError(
            "Google OAuth is not configured: missing " + ", ".join(missing)
        )
    response = session.post(
        TOKEN_URL,
        data={
            "client_id": common.env("GOOGLE_OAUTH_CLIENT_ID"),
            "client_secret": common.env("GOOGLE_OAUTH_CLIENT_SECRET"),
            "refresh_token": common.env("GOOGLE_OAUTH_REFRESH_TOKEN"),
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if not response.ok:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        error = str(payload.get("error") or "request_failed")
        description = str(payload.get("error_description") or "").strip()
        subtype = str(payload.get("error_subtype") or "").strip()
        detail = ": ".join(part for part in (error, description, subtype) if part)
        raise GoogleOAuthError(
            f"Google OAuth token refresh failed (HTTP {response.status_code}): {detail[:500]}"
        )
    token = str((response.json() or {}).get("access_token") or "").strip()
    if not token:
        raise GoogleOAuthError("Google OAuth refresh returned no access token")
    return token
