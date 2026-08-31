#!/usr/bin/env python3
"""Apply one signed exact legacy WordPress SEO remediation bundle."""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from campaign_run import load_business_profile, site_by_key
from reputation_core.approval_workflow import ExecutionLedger, verify_approval
from reputation_core.publication_seo import urls_equivalent


def _verify_legacy_url(payload: dict, *, session=requests) -> dict:
    redirect = session.get(payload["old_url"], allow_redirects=False, timeout=30)
    location = urljoin(payload["old_url"], redirect.headers.get("Location", ""))
    if redirect.status_code in {301, 302, 307, 308} and urls_equivalent(
        location, payload["expected_new_url"]
    ):
        return {"mode": "redirect", "target": location}
    if redirect.status_code == 403 and payload["site_key"] == "GUYROFE_COM":
        return {
            "mode": "browser_verification_required",
            "target": payload["expected_new_url"],
        }
    raise RuntimeError("Old URL did not redirect to the approved clean URL")


def apply_target(target: dict, *, session=requests) -> dict:
    payload = target["payload"]
    site = site_by_key(load_business_profile(), payload["site_key"])
    username = os.environ.get(site["user_env"], "")
    password = os.environ.get(site["app_password_env"], "")
    if not username or not password:
        raise RuntimeError("WordPress remediation credentials are not configured")
    endpoint = f"{site['base_url'].rstrip('/')}/wp-json/wp/v2/posts"
    auth = (username, password)
    response = session.get(
        endpoint,
        auth=auth,
        params={"slug": payload["old_slug"], "status": "publish", "context": "edit"},
        timeout=30,
    )
    response.raise_for_status()
    posts = response.json()
    if not posts:
        recovered = session.get(
            endpoint,
            auth=auth,
            params={
                "search": payload["new_title"],
                "status": "publish",
                "context": "edit",
                "per_page": 20,
            },
            timeout=30,
        )
        recovered.raise_for_status()
        posts = [
            item for item in recovered.json()
            if html.unescape((item.get("title") or {}).get("raw") or "").strip()
            in {payload["expected_current_title"], payload["new_title"]}
        ]
    if len(posts) != 1:
        raise RuntimeError("Exact legacy post was not found uniquely")
    post = posts[0]
    current_title = html.unescape((post.get("title") or {}).get("raw") or "").strip()
    if current_title not in {payload["expected_current_title"], payload["new_title"]}:
        raise PermissionError("Current title differs from the approved legacy payload")
    collision = session.get(
        endpoint,
        auth=auth,
        params={"slug": payload["new_slug"], "status": "publish", "context": "edit"},
        timeout=30,
    )
    collision.raise_for_status()
    if any(item.get("id") != post.get("id") for item in collision.json()):
        raise PermissionError("Approved clean slug collides with another post")
    updated = session.post(
        f"{endpoint}/{post['id']}",
        auth=auth,
        json={
            "title": payload["new_title"],
            "slug": payload["new_slug"],
            "excerpt": payload["meta_description"],
        },
        timeout=30,
    )
    updated.raise_for_status()
    result = updated.json()
    link = result.get("link") or ""
    if not urls_equivalent(link, payload["expected_new_url"]):
        raise RuntimeError("Provider returned a URL different from the approved clean URL")
    legacy = _verify_legacy_url(payload, session=session)
    return {"url": link, "old_url": payload["old_url"], "legacy": legacy}


def reconcile_target(target: dict, *, session=requests):
    """Read-only reconciliation for an accepted or untouched WordPress update."""
    payload = target["payload"]
    site = site_by_key(load_business_profile(), payload["site_key"])
    username = os.environ.get(site["user_env"], "")
    password = os.environ.get(site["app_password_env"], "")
    if not username or not password:
        raise RuntimeError("WordPress remediation credentials are not configured")
    endpoint = f"{site['base_url'].rstrip('/')}/wp-json/wp/v2/posts"
    auth = (username, password)
    clean = session.get(
        endpoint,
        auth=auth,
        params={"slug": payload["new_slug"], "status": "publish", "context": "edit"},
        timeout=30,
    )
    posts = None
    if clean.status_code != 403:
        clean.raise_for_status()
        try:
            posts = clean.json()
        except ValueError:
            if payload["site_key"] != "GUYROFE_COM":
                raise
    elif payload["site_key"] != "GUYROFE_COM":
        clean.raise_for_status()

    # The primary site's WAF may return an HTML challenge for a Unicode slug
    # query from GitHub Actions. Fall back to the authenticated title search,
    # then accept only the one post whose exact fields and URL match the signed
    # payload. This remains a read-only reconciliation path.
    if posts is None or len(posts) != 1:
        recovered = session.get(
            endpoint,
            auth=auth,
            params={
                "search": payload["new_title"],
                "status": "publish",
                "context": "edit",
                "per_page": 20,
            },
            timeout=30,
        )
        recovered.raise_for_status()
        posts = [
            item for item in recovered.json()
            if (
                html.unescape((item.get("title") or {}).get("raw") or "").strip()
                == payload["new_title"]
                and urls_equivalent(
                    item.get("link") or "", payload["expected_new_url"]
                )
            )
        ]
    if len(posts) == 1:
        post = posts[0]
        title = html.unescape((post.get("title") or {}).get("raw") or "").strip()
        excerpt = html.unescape((post.get("excerpt") or {}).get("raw") or "").strip()
        if (
            title != payload["new_title"]
            or excerpt != payload["meta_description"]
            or not urls_equivalent(post.get("link") or "", payload["expected_new_url"])
        ):
            raise RuntimeError("WordPress clean URL exists with unexpected fields")
        legacy = _verify_legacy_url(payload, session=session)
        return {"url": post["link"], "old_url": payload["old_url"], "legacy": legacy}
    if posts:
        raise RuntimeError("WordPress clean slug is not unique")
    legacy = session.get(
        endpoint,
        auth=auth,
        params={"slug": payload["old_slug"], "status": "publish", "context": "edit"},
        timeout=30,
    )
    legacy.raise_for_status()
    old_posts = legacy.json()
    if len(old_posts) == 1:
        title = html.unescape(
            (old_posts[0].get("title") or {}).get("raw") or ""
        ).strip()
        if title == payload["expected_current_title"]:
            return None
    raise RuntimeError("WordPress remediation state is ambiguous and requires review")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_path", type=Path)
    parser.add_argument("approval_record_path", type=Path)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=ROOT / "publication_receipts" / "seo_remediation_ledger.json",
    )
    args = parser.parse_args()
    bundle = json.loads(args.bundle_path.read_text(encoding="utf-8"))
    record = json.loads(args.approval_record_path.read_text(encoding="utf-8"))
    secret = os.environ.get("APPROVAL_SIGNING_SECRET", "")
    verify_approval(bundle, record, secret)
    if bundle.get("action_type") != "legacy_wordpress_seo_remediation":
        raise PermissionError("Approval bundle is not a legacy SEO remediation")
    ledger = ExecutionLedger(args.ledger)
    results = []
    for target in bundle["targets"]:
        results.append(ledger.execute(
            bundle,
            target,
            lambda _payload, _key, exact_target=target: apply_target(exact_target),
            reconciler=lambda _payload, _key, exact_target=target: (
                reconcile_target(exact_target)
            ),
        ))
    print(json.dumps({"updated": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
