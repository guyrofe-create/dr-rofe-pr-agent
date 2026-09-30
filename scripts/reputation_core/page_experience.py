"""Read-only PageSpeed/Core Web Vitals evidence adapter."""
from __future__ import annotations

import requests


PAGESPEED_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def fetch_page_experience(
    url: str,
    *,
    strategy: str = "mobile",
    api_key: str | None = None,
    session=requests,
) -> dict:
    params = {
        "url": url,
        "strategy": strategy,
        "category": ["performance", "seo", "accessibility"],
    }
    if api_key:
        params["key"] = api_key
    response = session.get(PAGESPEED_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    loading = (payload.get("loadingExperience") or {}).get("metrics", {})
    lighthouse = payload.get("lighthouseResult") or {}
    categories = lighthouse.get("categories") or {}

    def field(metric: str) -> dict:
        item = loading.get(metric) or {}
        return {
            "percentile": item.get("percentile"),
            "category": item.get("category"),
        }

    return {
        "url": url,
        "strategy": strategy,
        "field_data_available": bool(loading),
        "core_web_vitals": {
            "lcp_ms": field("LARGEST_CONTENTFUL_PAINT_MS"),
            "inp_ms": field("INTERACTION_TO_NEXT_PAINT"),
            "cls": field("CUMULATIVE_LAYOUT_SHIFT_SCORE"),
        },
        "scores": {
            name: category.get("score")
            for name, category in categories.items()
            if name in {"performance", "seo", "accessibility"}
        },
        "fetch_time": lighthouse.get("fetchTime"),
        "public_write_performed": False,
    }
