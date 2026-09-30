"""Canonical entity graph validation without public writes."""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_KEYS = {"si", "utm_source", "utm_medium", "utm_campaign", "sender_device", "is_from_webapp"}


def canonical_identity_url(value: str) -> str:
    parsed = urlparse(value.strip())
    query = urlencode([
        (key, item) for key, item in parse_qsl(parsed.query)
        if key.casefold() not in TRACKING_KEYS
    ])
    return urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path or "/",
        "",
        query,
        "",
    ))


def audit_entity_graph(profile: dict, registry: dict) -> dict:
    same_as = [canonical_identity_url(item) for item in profile.get("sameAs", [])]
    owner_urls = {
        canonical_identity_url(item["url"]): item.get("platform")
        for item in registry.get("owner_inventory", [])
        if item.get("url")
    }
    duplicates = sorted({url for url in same_as if same_as.count(url) > 1})
    shorteners = sorted(url for url in same_as if urlparse(url).netloc in {"bit.ly", "pin.it", "qr.ae"})
    unregistered = sorted(url for url in same_as if url not in owner_urls and not any(
        canonical_identity_url(site.get("base_url", "")) == url
        for site in profile.get("sites", []) if site.get("base_url")
    ) and "wikidata.org/" not in url)
    registered_missing = sorted(
        url for url in owner_urls
        if url not in same_as and urlparse(url).netloc not in {"x.com", "pin.it", "qr.ae"}
    )
    return {
        "status": "pass" if not duplicates and not shorteners and not unregistered else "review_required",
        "same_as_count": len(same_as),
        "duplicate_urls": duplicates,
        "short_or_redirect_urls": shorteners,
        "same_as_not_in_owner_inventory": unregistered,
        "registered_identity_candidates_missing_from_same_as": registered_missing,
        "public_write_performed": False,
    }
