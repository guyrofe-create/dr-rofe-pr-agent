"""Read-only Google Search Console evidence adapter.

Uses the product's existing Google OAuth refresh credentials. Missing
credentials or inaccessible properties degrade to an explicit skip; they never
block monitoring or invent measurements.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import quote

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"
SEARCH_ANALYTICS_URL = (
    "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
)


def refresh_google_access_token(
    client_id: str,
    client_secret: str,
    refresh_token: str,
    session=requests,
) -> str:
    response = session.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Google token refresh returned no access_token")
    return token


def fetch_search_console_rows(
    access_token: str,
    properties: list[str],
    *,
    end_date: date | None = None,
    days: int = 28,
    row_limit: int = 25000,
    session=requests,
) -> list[dict]:
    """Return normalized query/page rows for all accessible properties."""
    end = end_date or (date.today() - timedelta(days=3))
    start = end - timedelta(days=days - 1)
    payload = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query", "page"],
        "type": "web",
        "rowLimit": row_limit,
        "dataState": "final",
    }
    rows: list[dict] = []
    for site in properties:
        response = session.post(
            SEARCH_ANALYTICS_URL.format(site=quote(site, safe="")),
            headers={"Authorization": f"Bearer {access_token}"},
            json=payload,
            timeout=30,
        )
        if response.status_code in {403, 404}:
            continue
        response.raise_for_status()
        for item in response.json().get("rows", []):
            keys = item.get("keys") or []
            rows.append({
                "property": site,
                "query": keys[0] if keys else None,
                "page": keys[1] if len(keys) > 1 else None,
                "clicks": item.get("clicks", 0),
                "impressions": item.get("impressions", 0),
                "ctr": item.get("ctr", 0),
                "position": item.get("position", 100),
                "period": {"start": start.isoformat(), "end": end.isoformat()},
            })
    return rows
