"""Read-only Google Business Profile performance measurement."""
from __future__ import annotations

from datetime import date, timedelta

import requests


PERFORMANCE_API = "https://businessprofileperformance.googleapis.com/v1"
DAILY_METRICS = (
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "WEBSITE_CLICKS",
    "CALL_CLICKS",
    "BUSINESS_DIRECTION_REQUESTS",
)


def _location_resource(location: str) -> str:
    location_id = str(location).split("/locations/")[-1].strip("/")
    if not location_id:
        raise ValueError("Google Business location id is missing")
    return f"locations/{location_id}"


def _date_params(prefix: str, start: date, end: date) -> dict:
    params = {}
    for label, value in (("start_date", start), ("end_date", end)):
        params[f"{prefix}.{label}.year"] = value.year
        params[f"{prefix}.{label}.month"] = value.month
        params[f"{prefix}.{label}.day"] = value.day
    return params


def fetch_google_business_performance(
    access_token: str,
    location: str,
    *,
    end_date: date | None = None,
    session=requests,
) -> dict:
    """Fetch 28-day daily metrics and branded discovery keywords."""
    end_date = end_date or date.today()
    start_date = end_date - timedelta(days=27)
    resource = _location_resource(location)
    headers = {"Authorization": f"Bearer {access_token}"}
    daily_params = [("dailyMetrics", metric) for metric in DAILY_METRICS]
    daily_params.extend(_date_params("dailyRange", start_date, end_date).items())
    daily_response = session.get(
        f"{PERFORMANCE_API}/{resource}:fetchMultiDailyMetricsTimeSeries",
        headers=headers,
        params=daily_params,
        timeout=30,
    )
    daily_response.raise_for_status()

    start_month = start_date.replace(day=1)
    end_month = end_date.replace(day=1)
    keyword_params = {
        "monthlyRange.start_month.year": start_month.year,
        "monthlyRange.start_month.month": start_month.month,
        "monthlyRange.end_month.year": end_month.year,
        "monthlyRange.end_month.month": end_month.month,
        "pageSize": 100,
    }
    keywords = []
    while True:
        keyword_response = session.get(
            f"{PERFORMANCE_API}/{resource}/searchkeywords/impressions/monthly",
            headers=headers,
            params=keyword_params,
            timeout=30,
        )
        keyword_response.raise_for_status()
        payload = keyword_response.json()
        keywords.extend(payload.get("searchKeywordsCounts") or [])
        token = payload.get("nextPageToken")
        if not token:
            break
        keyword_params["pageToken"] = token

    return {
        "status": "ok",
        "location": resource,
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "daily_metrics": daily_response.json().get("multiDailyMetricTimeSeries") or [],
        "monthly_search_keywords": keywords,
    }
