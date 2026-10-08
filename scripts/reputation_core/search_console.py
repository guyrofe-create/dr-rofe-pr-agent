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
URL_INSPECTION_URL = (
    "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
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


def fetch_search_console_appearance_rows(
    access_token: str,
    properties: list[str],
    *,
    end_date: date | None = None,
    days: int = 28,
    row_limit: int = 25000,
    session=requests,
) -> list[dict]:
    """Return page-level Search appearance evidence, including AI types when exposed."""
    end = end_date or (date.today() - timedelta(days=3))
    start = end - timedelta(days=days - 1)
    payload = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["searchAppearance", "page"],
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
            appearance = keys[0] if keys else None
            rows.append({
                "property": site,
                "search_appearance": appearance,
                "page": keys[1] if len(keys) > 1 else None,
                "is_generative_ai": bool(
                    appearance and any(token in str(appearance).upper() for token in ("AI", "GENERATIVE"))
                ),
                "clicks": item.get("clicks", 0),
                "impressions": item.get("impressions", 0),
                "ctr": item.get("ctr", 0),
                "position": item.get("position", 100),
                "period": {"start": start.isoformat(), "end": end.isoformat()},
            })
    return rows


def inspect_search_console_urls(
    access_token: str,
    targets: list[dict],
    *,
    language_code: str = "he-IL",
    session=requests,
) -> list[dict]:
    """Inspect exact published URLs without requesting indexing or changing sites."""
    reports = []
    for target in targets:
        inspection_url = str(target.get("inspection_url") or "").strip()
        site_url = str(target.get("site_url") or "").strip()
        if not inspection_url or not site_url:
            reports.append({
                "inspection_url": inspection_url,
                "site_url": site_url,
                "status": "invalid_target",
            })
            continue
        response = session.post(
            URL_INSPECTION_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "inspectionUrl": inspection_url,
                "siteUrl": site_url,
                "languageCode": language_code,
            },
            timeout=30,
        )
        if response.status_code in {403, 404}:
            reports.append({
                "inspection_url": inspection_url,
                "site_url": site_url,
                "status": "inaccessible",
                "http_status": response.status_code,
            })
            continue
        response.raise_for_status()
        payload = response.json().get("inspectionResult", {})
        index = payload.get("indexStatusResult", {})
        rich = payload.get("richResultsResult", {})
        reports.append({
            "inspection_url": inspection_url,
            "site_url": site_url,
            "status": "ok",
            "verdict": index.get("verdict"),
            "coverage_state": index.get("coverageState"),
            "indexing_state": index.get("indexingState"),
            "robots_txt_state": index.get("robotsTxtState"),
            "page_fetch_state": index.get("pageFetchState"),
            "last_crawl_time": index.get("lastCrawlTime"),
            "google_canonical": index.get("googleCanonical"),
            "user_canonical": index.get("userCanonical"),
            "sitemap": index.get("sitemap", []),
            "referring_urls": index.get("referringUrls", []),
            "rich_results_verdict": rich.get("verdict"),
            "rich_result_items": rich.get("detectedItems", []),
            "mobile_usability": payload.get("mobileUsabilityResult", {}),
        })
    return reports
