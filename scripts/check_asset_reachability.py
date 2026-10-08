#!/usr/bin/env python3
"""Read-only public reachability check for every registered asset URL."""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests


ROOT = Path(__file__).resolve().parents[1]
ENTITY_VARIANTS = ("ד״ר גיא רופא", 'ד"ר גיא רופא', "גיא רופא", "Guy Rofe", "Dr. Guy Rofe")
OFFICIAL_HOSTS = {"guyrofe.com", "www.guyrofe.com", "drguyrofe.co.il", "www.drguyrofe.co.il", "drguyrofe.com", "www.drguyrofe.com"}
MAX_HTML_BYTES = 1_500_000


def classify(status: int | None, error: str | None) -> str:
    if error:
        return "network_or_provider_error"
    if status is None:
        return "unknown"
    if 200 <= status < 400:
        return "reachable"
    if status in {401, 403, 418, 429}:
        return "access_restricted_or_anti_bot"
    if status in {404, 410}:
        return "not_found"
    return "http_error"


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split()) or None


def _attributes(tag: str) -> dict[str, str]:
    return {
        name.casefold(): unescape(value)
        for name, _quote, value in re.findall(
            r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", tag, re.I | re.S
        )
    }


def audit_html(document: str, final_url: str) -> dict:
    """Extract public SEO/entity signals without executing scripts or logging in."""
    title = re.search(r"<title[^>]*>(.*?)</title>", document, re.I | re.S)
    meta_tags = [_attributes(tag) for tag in re.findall(r"<meta\b[^>]*>", document, re.I)]
    link_tags = [_attributes(tag) for tag in re.findall(r"<link\b[^>]*>", document, re.I)]
    description_value_raw = next((
        tag.get("content") for tag in meta_tags
        if tag.get("name", tag.get("property", "")).casefold() in {"description", "og:description"}
    ), None)
    canonical_value_raw = next((
        tag.get("href") for tag in link_tags
        if "canonical" in tag.get("rel", "").casefold().split()
    ), None)
    robots = [
        tag.get("content", "") for tag in meta_tags
        if tag.get("name", "").casefold() in {"robots", "googlebot"}
    ]
    headings = re.findall(r"<h1\b[^>]*>(.*?)</h1>", document, re.I | re.S)
    visible = _clean_text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", document, flags=re.I | re.S)) or ""
    links = re.findall(r'<a\b[^>]+href=["\']([^"\']+)', document, re.I)
    link_hosts = {
        urlparse(urljoin(final_url, link)).hostname
        for link in links
        if urlparse(urljoin(final_url, link)).hostname
    }
    schema_types = sorted(set(re.findall(r'["\']@type["\']\s*:\s*["\']([^"\']+)', document)))
    canonical_url = urljoin(final_url, canonical_value_raw) if canonical_value_raw else None
    robots_value = ", ".join(robots).casefold()
    title_value = _clean_text(title.group(1)) if title else None
    description_value = _clean_text(description_value_raw)
    entity_in_title = bool(title_value and any(name.casefold() in title_value.casefold() for name in ENTITY_VARIANTS))
    entity_in_page = any(name.casefold() in visible.casefold() for name in ENTITY_VARIANTS)
    official_link_present = bool(link_hosts & OFFICIAL_HOSTS)
    issues = []
    if "noindex" in robots_value:
        issues.append("noindex")
    if not title_value:
        issues.append("missing_title")
    if not description_value:
        issues.append("missing_meta_description")
    if not entity_in_page:
        issues.append("missing_entity_name")
    if not canonical_url:
        issues.append("missing_canonical")
    if len(headings) != 1:
        issues.append("h1_count_not_one")
    return {
        "content_audit": "complete",
        "title": title_value,
        "meta_description": description_value,
        "canonical": canonical_url,
        "robots": robots,
        "noindex": "noindex" in robots_value,
        "h1_count": len(headings),
        "h1": [_clean_text(item) for item in headings[:3]],
        "entity_in_title": entity_in_title,
        "entity_in_page": entity_in_page,
        "official_link_present": official_link_present,
        "schema_types": schema_types,
        "seo_issues": issues,
    }


def check(asset: dict, *, timeout: int = 12) -> dict:
    url = asset.get("url")
    if not url:
        return {"platform": asset.get("platform"), "url": None,
                "http_status": None, "reachability": "missing_url"}
    try:
        response = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; reputation-asset-audit/1.0)"},
            stream=True,
        )
        status = response.status_code
        final_url = response.url
        content_type = response.headers.get("content-type", "")
        encoding = response.encoding or "utf-8"
        body = b""
        if 200 <= status < 400 and "html" in content_type.casefold():
            for chunk in response.iter_content(chunk_size=65536):
                body += chunk
                if len(body) >= MAX_HTML_BYTES:
                    body = body[:MAX_HTML_BYTES]
                    break
        response.close()
        result = {
            "platform": asset.get("platform"), "url": url,
            "http_status": status, "final_url": final_url,
            "reachability": classify(status, None),
            "content_type": content_type,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if body:
            result.update(audit_html(body.decode(encoding, errors="replace"), final_url))
        else:
            result.update({"content_audit": "manual_required", "seo_issues": []})
        return result
    except requests.RequestException as exc:
        return {
            "platform": asset.get("platform"), "url": url,
            "http_status": None, "reachability": classify(None, str(exc)),
            "error_type": type(exc).__name__,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "data" / "asset_registry.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    assets = registry.get("assets", [])
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        futures = [pool.submit(check, asset) for asset in assets]
        for future in as_completed(futures):
            rows.append(future.result())
    order = {asset.get("platform"): index for index, asset in enumerate(assets)}
    rows.sort(key=lambda row: order.get(row.get("platform"), 9999))
    counts = {}
    for row in rows:
        key = row["reachability"]
        counts[key] = counts.get(key, 0) + 1
    payload = {
        "version": 2,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "asset_count": len(rows),
        "summary": counts,
        "credentials_used": False,
        "public_changes_made": False,
        "assets": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset_count": len(rows), "summary": counts}))


if __name__ == "__main__":
    main()
