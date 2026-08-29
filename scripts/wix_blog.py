"""Exact-approval Wix Blog publisher using the official Wix REST APIs."""
from __future__ import annotations

import html as html_lib
import os
import re
from urllib.parse import quote, unquote, urljoin, urlparse

import requests

try:
    from reputation_core.approval_workflow import DefinitiveProviderRejection
except ModuleNotFoundError:  # Imported as scripts.wix_blog in unit tests.
    from .reputation_core.approval_workflow import DefinitiveProviderRejection


API_ROOT = "https://www.wixapis.com"


class WixAPIError(DefinitiveProviderRejection):
    """A conclusive Wix 4xx response with non-sensitive provider detail."""


def _error_detail(response) -> str:
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = {}
    details = payload.get("details") if isinstance(payload, dict) else {}
    details = details if isinstance(details, dict) else {}
    validation = details.get("validationError") or {}
    application = details.get("applicationError") or {}
    violations = validation.get("fieldViolations") or []
    parts = [
        payload.get("message") if isinstance(payload, dict) else None,
        application.get("description") if isinstance(application, dict) else None,
        str(violations) if violations else None,
    ]
    return " | ".join(str(part) for part in parts if part)[:500] or "no provider detail"


def _raise_for_status(response, action: str) -> None:
    if response.status_code < 400:
        return
    detail = f"Wix {action} failed: HTTP {response.status_code}: {_error_detail(response)}"
    if response.status_code in {400, 401, 403, 404, 422}:
        raise WixAPIError(detail)
    response.raise_for_status()


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


def _urls_equivalent(first: str, second: str) -> bool:
    def normalize(value: str) -> str:
        parsed = urlparse(unquote(value or ""))
        return (
            parsed.netloc.lower().removeprefix("www."),
            re.sub(r"/+", "/", parsed.path).rstrip("/"),
        )
    return normalize(first) == normalize(second)


def _legacy_resolution(old_url: str, expected_url: str, *, session=requests) -> dict:
    response = session.get(old_url, allow_redirects=False, timeout=30)
    location = urljoin(old_url, response.headers.get("Location", ""))
    if response.status_code in {301, 302, 307, 308} and _urls_equivalent(
        location, expected_url
    ):
        return {"mode": "redirect", "target": location}
    if response.status_code == 200:
        match = re.search(
            r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
            response.text,
            re.I,
        ) or re.search(
            r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
            response.text,
            re.I,
        )
        canonical = html_lib.unescape(match.group(1)).strip() if match else ""
        if _urls_equivalent(canonical, expected_url):
            return {"mode": "canonical_alias", "target": canonical}
    raise RuntimeError("Old Wix URL did not resolve to the approved clean URL")


def _existing_post(site: dict, slug: str, *, session=requests):
    response = session.get(
        f"{API_ROOT}/blog/v3/posts/slugs/{quote(slug, safe='')}",
        headers=_headers(site),
        timeout=25,
    )
    if response.status_code == 404:
        return None
    _raise_for_status(response, "published-post lookup")
    return (response.json() or {}).get("post")


def reconcile(site: dict, *, slug: str, expected_url: str, session=requests):
    """Return a receipt if the approved slug exists, otherwise confirm absence."""
    if expected_url.rstrip("/") != public_post_url(site, slug).rstrip("/"):
        raise PermissionError("Approved Wix URL does not match the configured site route")
    if not _existing_post(site, slug, session=session):
        return None
    return {"url": expected_url}


def _member_id(site: dict, *, session=requests) -> str:
    env_name = str(site.get("member_id_env") or "").strip()
    configured_id = os.environ.get(env_name, "").strip() if env_name else ""
    if configured_id:
        return configured_id
    response = session.get(
        f"{API_ROOT}/v3/posts",
        headers=_headers(site),
        params={"paging.limit": 100},
        timeout=25,
    )
    _raise_for_status(response, "blog-author discovery")
    member_ids = {
        str(post.get("memberId") or "").strip()
        for post in (response.json() or {}).get("posts", [])
        if str(post.get("memberId") or "").strip()
    }
    if len(member_ids) == 1:
        return next(iter(member_ids))
    if not member_ids:
        raise WixAPIError(
            "Wix create-draft readiness failed: no blog owner memberId was found; "
            f"configure {env_name or 'a site member_id_env'}"
        )
    raise WixAPIError(
        "Wix create-draft readiness failed: multiple blog owner memberIds were found; "
        f"configure the exact author in {env_name or 'a site member_id_env'}"
    )


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
    _raise_for_status(response, "Ricos conversion")
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
    member_id = _member_id(site, session=session)
    document = _to_ricos(site, html, session=session)
    response = session.post(
        f"{API_ROOT}/blog/v3/draft-posts",
        headers=_headers(site),
        json={
            "draftPost": {
                "title": title,
                "memberId": member_id,
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
    _raise_for_status(response, "draft creation")
    created = (response.json() or {}).get("draftPost") or {}
    if not created.get("id"):
        raise RuntimeError("Wix accepted no identifiable draft/post receipt")
    return expected_url


def update_published(
    site: dict,
    *,
    old_slug: str,
    expected_current_title: str,
    title: str,
    excerpt: str,
    slug: str,
    old_url: str,
    expected_url: str,
    session=requests,
) -> dict:
    """Update one exact published Wix post and verify its legacy redirect."""
    if expected_url.rstrip("/") != public_post_url(site, slug).rstrip("/"):
        raise PermissionError("Approved Wix URL does not match the configured site route")
    post = _existing_post(site, old_slug, session=session)
    if not post:
        post = _existing_post(site, slug, session=session)
    if not post or post.get("title") not in {expected_current_title, title}:
        raise PermissionError("Exact approved Wix post was not found")
    collision = _existing_post(site, slug, session=session)
    if collision and collision.get("id") != post.get("id"):
        raise PermissionError("Approved Wix slug collides with another post")
    post_id = str(post.get("id") or "").strip()
    if not post_id:
        raise RuntimeError("Wix returned no post ID for the approved legacy post")
    updated = session.patch(
        f"{API_ROOT}/blog/v3/draft-posts/{post_id}",
        headers=_headers(site),
        json={
            "draftPost": {
                "id": post_id,
                "title": title,
                "excerpt": excerpt[:500],
                "seoSlug": slug,
            },
        },
        timeout=30,
    )
    _raise_for_status(updated, "draft update")
    published = session.post(
        f"{API_ROOT}/blog/v3/draft-posts/{post_id}/publish",
        headers=_headers(site),
        timeout=40,
    )
    _raise_for_status(published, "draft publication")
    verified = _existing_post(site, slug, session=session)
    if not verified or verified.get("title") != title:
        raise RuntimeError("Wix did not return the exact updated public post")
    resolution = _legacy_resolution(old_url, expected_url, session=session)
    return {"url": expected_url, "old_url": old_url, "legacy": resolution}


def reconcile_published_update(
    site: dict,
    *,
    old_slug: str,
    expected_current_title: str,
    title: str,
    excerpt: str,
    slug: str,
    old_url: str,
    expected_url: str,
    session=requests,
):
    """Read-only reconciliation for a possibly accepted Wix update."""
    current = _existing_post(site, slug, session=session)
    if current:
        if current.get("title") != title or current.get("excerpt") != excerpt[:500]:
            raise RuntimeError("Wix clean slug exists with unexpected approved fields")
        resolution = _legacy_resolution(old_url, expected_url, session=session)
        return {"url": expected_url, "old_url": old_url, "legacy": resolution}
    legacy = _existing_post(site, old_slug, session=session)
    if legacy and legacy.get("title") == expected_current_title:
        return None
    raise RuntimeError("Wix remediation state is ambiguous and requires review")
