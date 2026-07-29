"""Exact-approval Wix Blog publisher using the official Wix REST APIs."""
from __future__ import annotations

import os
from urllib.parse import quote

import requests


API_ROOT = "https://www.wixapis.com"


def configured(site: dict) -> bool:
    return all(
        os.environ.get(site.get(field, ""), "").strip()
        for field in ("api_key_env", "site_id_env")
    )


def _headers(site: dict) -> dict:
    api_key = os.environ.get(site["api_key_env"], "").strip()
    site_id = os.environ.get(site["site_id_env"], "").strip()
    if not api_key or not site_id:
        raise RuntimeError(f"Wix publisher is not configured for {site['key']}")
    return {
        "Authorization": api_key,
        "wix-site-id": site_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def public_post_url(site: dict, slug: str) -> str:
    route = str(site.get("post_route") or "post").strip("/")
    return f"{site['base_url'].rstrip('/')}/{route}/{slug}"


def _existing_post(site: dict, slug: str, *, session=requests):
    response = session.get(
        f"{API_ROOT}/blog/v3/posts/slugs/{quote(slug, safe='')}",
        headers=_headers(site),
        timeout=25,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return (response.json() or {}).get("post")


def _to_ricos(site: dict, html: str, *, session=requests) -> dict:
    response = session.post(
        f"{API_ROOT}/ricos/v1/ricos-document/convert/to-ricos",
        headers=_headers(site),
        json={
            "html": html,
            "options": {"plugins": ["heading", "image", "link"]},
        },
        timeout=30,
    )
    response.raise_for_status()
    document = (response.json() or {}).get("document")
    if not document or not document.get("nodes"):
        raise RuntimeError("Wix returned no Ricos document for the approved article")
    return document


def publish(
    site: dict,
    *,
    title: str,
    html: str,
    excerpt: str,
    slug: str,
    expected_url: str,
    session=requests,
) -> str:
    """Publish once by slug; only provider acceptance returns a public URL."""
    if expected_url.rstrip("/") != public_post_url(site, slug).rstrip("/"):
        raise PermissionError("Approved Wix URL does not match the configured site route")
    existing = _existing_post(site, slug, session=session)
    if existing:
        return expected_url
    document = _to_ricos(site, html, session=session)
    response = session.post(
        f"{API_ROOT}/blog/v3/draft-posts",
        headers=_headers(site),
        json={
            "draftPost": {
                "title": title,
                "excerpt": excerpt[:500],
                "seoSlug": slug,
                "language": "he",
                "commentingEnabled": False,
                "richContent": document,
            },
            "publish": True,
        },
        timeout=40,
    )
    response.raise_for_status()
    created = (response.json() or {}).get("draftPost") or {}
    if not created.get("id"):
        raise RuntimeError("Wix accepted no identifiable draft/post receipt")
    return expected_url
