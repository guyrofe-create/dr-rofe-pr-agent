"""Read-only Google Business Profile performance measurement."""
from __future__ import annotations

from datetime import date, timedelta

import requests


PERFORMANCE_API = "https://businessprofileperformance.googleapis.com/v1"
BUSINESS_INFORMATION_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
DAILY_METRICS = (
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
    "WEBSITE_CLICKS",
    "CALL_CLICKS",
    "BUSINESS_DIRECTION_REQUESTS",
)

SEARCH_IMPRESSION_METRICS = {
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
}
MAPS_IMPRESSION_METRICS = {
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
}
ENGAGEMENT_METRICS = {
    "WEBSITE_CLICKS", "CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS",
}


def _location_resource(location: str) -> str:
    location_id = str(location).split("/locations/")[-1].strip("/")
    if not location_id:
        raise ValueError("Google Business location id is missing")
    return f"locations/{location_id}"


def fetch_google_business_profile_details(
    access_token: str,
    location: str,
    *,
    session=requests,
) -> dict:
    """Read the public-facing business model fields; never edit them."""
    resource = _location_resource(location)
    response = session.get(
        f"{BUSINESS_INFORMATION_API}/{resource}",
        headers={"Authorization": f"Bearer {access_token}"},
        params={
            "readMask": (
                "name,title,categories,storefrontAddress,serviceArea,"
                "regularHours,websiteUri,phoneNumbers,profile,metadata"
            )
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _date_params(prefix: str, start: date, end: date) -> dict:
    params = {}
    for label, value in (("start_date", start), ("end_date", end)):
        params[f"{prefix}.{label}.year"] = value.year
        params[f"{prefix}.{label}.month"] = value.month
        params[f"{prefix}.{label}.day"] = value.day
    return params


def _metric_totals(daily_metrics: list[dict]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for group in daily_metrics:
        for series in group.get("dailyMetricTimeSeries") or []:
            metric = str(series.get("dailyMetric") or "")
            if not metric:
                continue
            values = (series.get("timeSeries") or {}).get("datedValues") or []
            total = 0
            for row in values:
                try:
                    total += int(row.get("value") or 0)
                except (TypeError, ValueError):
                    continue
            totals[metric] = totals.get(metric, 0) + total
    return totals


def summarize_google_business_performance(
    daily_metrics: list[dict], monthly_keywords: list[dict]
) -> dict:
    """Separate real GBP visibility from ordinary organic web ranking."""
    totals = _metric_totals(daily_metrics)
    search_impressions = sum(totals.get(name, 0) for name in SEARCH_IMPRESSION_METRICS)
    maps_impressions = sum(totals.get(name, 0) for name in MAPS_IMPRESSION_METRICS)
    engagements = sum(totals.get(name, 0) for name in ENGAGEMENT_METRICS)
    total_impressions = search_impressions + maps_impressions
    recommendations = []
    if total_impressions == 0:
        visibility = "no_measured_visibility"
        recommendations.append(
            "Verify profile eligibility, public state, primary category, address or service area, and exact business identity."
        )
    else:
        visibility = "visible_in_google_search_or_maps"
        recommendations.append(
            "Treat organic web rank and Business Profile visibility as separate surfaces."
        )
        if maps_impressions < max(10, search_impressions * 0.1):
            recommendations.append(
                "Audit local relevance signals: primary category, real office address or service area, hours, landing page and authoritative listing consistency."
            )
        if engagements == 0:
            recommendations.append(
                "Audit the profile landing page, contact actions, photos and information completeness."
            )
    return {
        "visibility_status": visibility,
        "metric_totals": totals,
        "search_impressions": search_impressions,
        "maps_impressions": maps_impressions,
        "total_impressions": total_impressions,
        "engagements": engagements,
        "keyword_data_status": (
            "available" if monthly_keywords else "not_returned_by_api"
        ),
        "organic_page_one_status": "not_measured_by_google_business_api",
        "local_rank_weak": total_impressions == 0,
        "recommendations": recommendations,
    }


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

    daily_metrics = daily_response.json().get("multiDailyMetricTimeSeries") or []
    return {
        "status": "ok",
        "location": resource,
        "period": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "daily_metrics": daily_metrics,
        "monthly_search_keywords": keywords,
        "summary": summarize_google_business_performance(daily_metrics, keywords),
    }
