#!/usr/bin/env python3
"""Read-only Wix URL/content audit used to keep publication gates honest."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from reputation_core.installation import data_path


ROOT = Path(__file__).resolve().parents[1]
LEGACY_SLUG = re.compile(r"(?:^|/)(?:copy-of-|blank(?:-|$))", re.IGNORECASE)


def _urls_from_sitemap(url: str, *, session=requests) -> list[str]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    locations = [
        element.text.strip()
        for element in root.iter()
        if element.tag.endswith("loc") and element.text
    ]
    if root.tag.endswith("sitemapindex"):
        urls = []
        for child in locations:
            try:
                urls.extend(_urls_from_sitemap(child, session=session))
            except requests.RequestException:
                continue
        return urls
    return locations


def classify_urls(urls: list[str]) -> dict:
    legacy = []
    appointment_or_service = []
    for url in urls:
        path = urlparse(url).path.strip("/")
        if LEGACY_SLUG.search(path):
            legacy.append(url)
        if "/service-page/" in f"/{path}/" or any(
            token in path.lower()
            for token in ("booking", "appointment", "קביעת-תור", "ייעוץ")
        ):
            appointment_or_service.append(url)
    return {
        "total_indexable_urls": len(set(urls)),
        "legacy_or_placeholder_urls": sorted(set(legacy)),
        "service_or_booking_urls_requiring_factual_review": sorted(
            set(appointment_or_service)
        ),
    }


def audit_site(site: dict, *, session=requests) -> dict:
    urls = _urls_from_sitemap(
        f"{site['base_url'].rstrip('/')}/sitemap.xml",
        session=session,
    )
    classification = classify_urls(urls)
    blockers = []
    if classification["legacy_or_placeholder_urls"]:
        blockers.append("legacy_or_placeholder_urls")
    if classification["service_or_booking_urls_requiring_factual_review"]:
        blockers.append("service_or_booking_claims_require_review")
    result = {
        "site_key": site["key"],
        "base_url": site["base_url"],
        "role": site.get("role"),
        "audited_at": datetime.now(timezone.utc).isoformat(),
        **classification,
        "publication_blockers": blockers,
        "audit_passed": not blockers,
        "changes_performed": False,
    }
    api_key = os.environ.get(site.get("api_key_env", ""), "").strip()
    site_id = os.environ.get(site.get("site_id_env", ""), "").strip()
    if api_key and site_id:
        response = session.get(
            "https://www.wixapis.com/blog/v3/posts",
            headers={"Authorization": api_key, "wix-site-id": site_id},
            params={"paging.limit": 100},
            timeout=30,
        )
        response.raise_for_status()
        result["published_blog_posts_visible_to_api"] = len(
            (response.json() or {}).get("posts", [])
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-key", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(
        data_path("business_profile.json").read_text(encoding="utf-8")
    )
    site = next(
        (item for item in profile["sites"] if item.get("key") == args.site_key),
        None,
    )
    if not site or site.get("platform") != "wix":
        raise SystemExit(f"Unknown Wix site key: {args.site_key}")
    result = audit_site(site)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
