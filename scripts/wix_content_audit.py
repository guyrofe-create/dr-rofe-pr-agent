#!/usr/bin/env python3
"""Read-only Wix URL/content audit used to keep publication gates honest."""
from __future__ import annotations

import argparse
import hashlib
import html
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
GENERIC_PAGE_TITLE = re.compile(
    r"^(?:blank|copy[\s-]*of|homepage|home|untitled)(?:[\s|–—-].*)?$",
    re.IGNORECASE,
)


def _urls_from_sitemap(url: str, *, session=requests) -> list[str]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    if root.tag.endswith("sitemapindex"):
        urls = []
        for sitemap in root:
            location = next(
                (
                    element.text.strip()
                    for element in sitemap
                    if element.tag.endswith("loc") and element.text
                ),
                None,
            )
            if not location:
                continue
            try:
                urls.extend(_urls_from_sitemap(location, session=session))
            except requests.RequestException:
                continue
        return urls
    return [
        element.text.strip()
        for url_element in root
        if url_element.tag.endswith("url")
        for element in url_element
        if element.tag.endswith("loc") and element.text
    ]


def _tag_attribute(document: str, tag_name: str, match: dict, target: str) -> str:
    for candidate in re.finditer(fr"<{tag_name}\b[^>]*>", document, re.IGNORECASE):
        tag = candidate.group(0)
        if not all(
            re.search(fr"""{name}=["']{re.escape(value)}["']""", tag, re.IGNORECASE)
            for name, value in match.items()
        ):
            continue
        value = re.search(fr"""{target}=["']([^"']*)""", tag, re.IGNORECASE)
        if value:
            return html.unescape(value.group(1)).strip()
    return ""


def _public_page_metadata(url: str, *, session=requests) -> dict:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    document = response.text
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        document,
        re.IGNORECASE | re.DOTALL,
    )
    title = ""
    if title_match:
        title = html.unescape(re.sub(r"<[^>]+>", " ", title_match.group(1)))
        title = " ".join(title.split())
    description = _tag_attribute(
        document,
        "meta",
        {"name": "description"},
        "content",
    ) or _tag_attribute(
        document,
        "meta",
        {"property": "og:description"},
        "content",
    )
    description = " ".join(description.split())
    fingerprint = hashlib.sha256(
        f"{title}\n{description}".encode("utf-8")
    ).hexdigest()
    return {
        "title": title,
        "description": description,
        "metadata_sha256": fingerprint,
    }


def _substantive_title(title: str) -> bool:
    normalized = re.sub(r"\s*\|\s*homepage\s*$", "", title, flags=re.IGNORECASE)
    normalized = " ".join(normalized.split())
    return bool(normalized and not GENERIC_PAGE_TITLE.fullmatch(normalized))


def classify_urls(
    urls: list[str],
    *,
    metadata_by_url: dict[str, dict] | None = None,
    reviewed_service_metadata: dict[str, str] | None = None,
) -> dict:
    metadata_by_url = metadata_by_url or {}
    reviewed_service_metadata = reviewed_service_metadata or {}
    legacy_slugs = []
    placeholder_pages = []
    service_pages = []
    unreviewed_service_pages = []
    for url in urls:
        path = urlparse(url).path.strip("/")
        if LEGACY_SLUG.search(path):
            legacy_slugs.append(url)
            if not _substantive_title(metadata_by_url.get(url, {}).get("title", "")):
                placeholder_pages.append(url)
        if "/service-page/" in f"/{path}/" or any(
            token in path.lower()
            for token in ("booking", "appointment", "קביעת-תור", "ייעוץ")
        ):
            service_pages.append(url)
            observed = metadata_by_url.get(url, {}).get("metadata_sha256")
            if not observed or reviewed_service_metadata.get(url) != observed:
                unreviewed_service_pages.append(url)
    return {
        "total_indexable_urls": len(set(urls)),
        "legacy_slug_urls": sorted(set(legacy_slugs)),
        "legacy_or_placeholder_urls": sorted(set(placeholder_pages)),
        "service_or_booking_urls": sorted(set(service_pages)),
        "service_or_booking_urls_requiring_factual_review": sorted(
            set(unreviewed_service_pages)
        ),
    }


def audit_site(site: dict, *, session=requests) -> dict:
    urls = _urls_from_sitemap(
        f"{site['base_url'].rstrip('/')}/sitemap.xml",
        session=session,
    )
    candidates = [
        url
        for url in urls
        if LEGACY_SLUG.search(urlparse(url).path.strip("/"))
        or "/service-page/" in f"/{urlparse(url).path.strip('/')}/"
    ]
    metadata_by_url = {
        url: _public_page_metadata(url, session=session)
        for url in candidates
    }
    classification = classify_urls(
        urls,
        metadata_by_url=metadata_by_url,
        reviewed_service_metadata=site.get("reviewed_service_metadata", {}),
    )
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
        "public_metadata_checked": len(metadata_by_url),
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
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="Exit non-zero after writing the report when publication blockers exist.",
    )
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
    if args.require_pass and not result["audit_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
