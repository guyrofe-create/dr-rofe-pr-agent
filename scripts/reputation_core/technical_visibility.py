"""Read-only technical visibility and post-publication lifecycle helpers."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests


FINAL_PROVIDER_STATES = {"LIVE", "REJECTED", "FAILED"}


def fetch_sitemap_urls(base_url: str, *, session=requests, maximum: int = 5000) -> list[str]:
    """Read a site's public sitemap/index without making any public change."""
    root_url = base_url.rstrip("/") + "/sitemap.xml"
    pending = [root_url]
    visited = set()
    urls = []
    while pending and len(urls) < maximum:
        current = pending.pop(0)
        if current in visited:
            continue
        visited.add(current)
        response = session.get(current, timeout=20, headers={
            "User-Agent": "ReputationAgent-TechnicalAudit/1.0"
        })
        response.raise_for_status()
        document = ET.fromstring(response.content)
        locations = [
            (node.text or "").strip()
            for node in document.iter()
            if node.tag.endswith("loc") and (node.text or "").strip()
        ]
        if document.tag.endswith("sitemapindex"):
            pending.extend(locations)
        else:
            urls.extend(locations)
    return list(dict.fromkeys(urls))[:maximum]


def normalize_provider_state(receipt: dict) -> dict:
    """Do not confuse provider acceptance/processing with a live publication."""
    raw = str(
        receipt.get("provider_state")
        or receipt.get("state")
        or receipt.get("status")
        or "UNKNOWN"
    ).upper()
    aliases = {
        "PUBLISHED": "ACCEPTED",
        "SUCCESS": "ACCEPTED",
        "SKIPPED_DUPLICATE": "ACCEPTED",
        "PROCESSING": "PROCESSING",
        "PENDING": "PROCESSING",
        "VERIFIED": "LIVE",
        "VERIFIED_CONTENT": "LIVE",
        "FAILED": "FAILED",
        "REJECTED": "REJECTED",
    }
    state = aliases.get(raw, raw)
    return {
        "provider_state": state,
        "final": state in FINAL_PROVIDER_STATES,
        "live": state == "LIVE",
        "requires_reconciliation": state in {"ACCEPTED", "PROCESSING", "UNKNOWN"},
    }


def audit_sitemap_membership(url: str, sitemap_urls: list[str]) -> dict:
    normalized = url.rstrip("/")
    matches = [item for item in sitemap_urls if str(item).rstrip("/") == normalized]
    return {
        "url": url,
        "present": bool(matches),
        "matched_urls": matches,
        "checked_count": len(sitemap_urls),
    }


def audit_structured_data(html: str) -> dict:
    types = set(re.findall(r'"@type"\s*:\s*"([^"]+)"', html or ""))
    required = {"Article", "Person"}
    recommended = {"BreadcrumbList", "ImageObject", "WebSite"}
    return {
        "types": sorted(types),
        "required_present": sorted(required & types),
        "required_missing": sorted(required - types),
        "recommended_missing": sorted(recommended - types),
        "passed": not (required - types),
    }


def build_publication_lifecycle(
    *,
    url: str,
    receipt: dict | None = None,
    live_verification: dict | None = None,
    sitemap_audit: dict | None = None,
    inspection: dict | None = None,
    search_console_row: dict | None = None,
) -> dict:
    provider = normalize_provider_state(receipt or {})
    inspection = inspection or {}
    coverage = str(inspection.get("coverage_state") or "").casefold()
    verdict = str(inspection.get("verdict") or "").upper()
    indexed = verdict == "PASS" or "indexed" in coverage
    live_state = str((live_verification or {}).get("state") or "")
    live = live_state in {"verified_content", "live_url_content_unconfirmed", "live"}
    impressions = float((search_console_row or {}).get("impressions") or 0)
    query = (search_console_row or {}).get("query")
    stages = {
        "provider_accepted": provider["provider_state"] in {
            "ACCEPTED", "PROCESSING", "LIVE"
        },
        "live_verified": live,
        "sitemap_present": bool((sitemap_audit or {}).get("present")),
        "google_crawled": bool(inspection.get("last_crawl_time")),
        "google_indexed": indexed,
        "search_impressions": impressions > 0,
        "brand_query_visibility": bool(query and impressions > 0),
    }
    first_incomplete = next((name for name, passed in stages.items() if not passed), None)
    return {
        "url": url,
        "host": urlparse(url).netloc.lower().removeprefix("www."),
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "stages": stages,
        "first_incomplete_stage": first_incomplete,
        "complete": all(stages.values()),
        "inspection": inspection,
        "sitemap": sitemap_audit or {},
        "search_console": search_console_row or {},
    }


def content_refresh_reasons(
    *,
    source_age_days: int | None = None,
    broken_citations: int = 0,
    guideline_changed: bool = False,
    position_change: float | None = None,
) -> list[str]:
    reasons = []
    if source_age_days is not None and source_age_days >= 730:
        reasons.append("medical_source_older_than_two_years")
    if broken_citations:
        reasons.append("broken_citations")
    if guideline_changed:
        reasons.append("guideline_changed")
    if position_change is not None and position_change <= -3:
        reasons.append("material_rank_loss")
    return reasons


def build_indexnow_payload(urls: list[str], key: str, key_location: str) -> dict:
    """Prepare a Bing/IndexNow request; callers retain external-write approval."""
    clean = list(dict.fromkeys(url for url in urls if url.startswith("https://")))
    if not clean:
        raise ValueError("At least one HTTPS URL is required")
    host = urlparse(clean[0]).netloc
    if any(urlparse(url).netloc != host for url in clean):
        raise ValueError("One IndexNow payload may contain URLs from one host only")
    return {"host": host, "key": key, "keyLocation": key_location, "urlList": clean}
