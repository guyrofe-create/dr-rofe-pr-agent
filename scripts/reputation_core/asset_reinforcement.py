"""Evidence-led linking plan for coordinated owned-asset reinforcement."""
from __future__ import annotations

from urllib.parse import urlparse


def _host(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def build_asset_reinforcement_plan(
    *,
    canonical_url: str,
    canonical_name: str,
    profile_url: str,
    search_target: dict,
    same_site_links: list[dict],
    assets: list[dict],
) -> dict:
    """Describe exactly which assets a publication strengthens and why."""
    host = _host(canonical_url)
    current_asset = next(
        (item for item in assets if _host(item.get("url")) == host),
        {},
    )
    identity = {
        "url": profile_url,
        "anchor": canonical_name,
        "placement": "linked_author_byline_and_author_box",
        "reason": "stable identity disambiguation",
    }
    internal = [
        {
            "url": item["url"],
            "anchor": item["title"],
            "placement": "related_reading",
            "reason": "same-site topical discovery and crawl path",
        }
        for item in same_site_links[:2]
    ]
    # Only exact pages are eligible for a cross-property editorial link. A
    # homepage/profile from the registry is not injected merely to manufacture
    # a network. Such a link can still be proposed later with reader-value
    # evidence and will then appear in the exact approval payload.
    complementary = []
    baseline = {
        "asset_id": current_asset.get("asset_id") or current_asset.get("id"),
        "asset_url": current_asset.get("url") or canonical_url,
        "observed_position": current_asset.get("observed_position"),
        "observed_query": current_asset.get("observed_query"),
        "observed_at": current_asset.get("observed_at"),
    }
    return {
        "primary_asset": {
            "url": canonical_url,
            "host": host,
            "reason": "canonical destination receiving the original publication",
        },
        "target_queries": [
            search_target.get("primary_query"),
            *(search_target.get("entity_queries") or []),
        ],
        "identity_link": identity,
        "same_site_links": internal,
        "complementary_owned_asset_links": complementary,
        "cross_property_rule": (
            "At most one contextually relevant exact page; never add a homepage "
            "or reciprocal link solely for ranking."
        ),
        "baseline": baseline,
        "measurement_windows_days": [7, 28, 42],
        "tactic_change_after_days_without_improvement": 42,
    }


def approved_reinforcement_links(plan: dict) -> list[dict]:
    """Return only links whose placement is explicitly in the approved article."""
    links = []
    for item in plan.get("same_site_links", []):
        links.append({"title": item["anchor"], "url": item["url"]})
    for item in plan.get("complementary_owned_asset_links", [])[:1]:
        if item.get("reader_value_evidence"):
            links.append({"title": item["anchor"], "url": item["url"]})
    return links
