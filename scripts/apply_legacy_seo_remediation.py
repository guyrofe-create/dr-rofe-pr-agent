#!/usr/bin/env python3
"""Apply one signed exact legacy WordPress SEO remediation bundle."""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from campaign_run import load_business_profile, site_by_key
from reputation_core.approval_workflow import ExecutionLedger, verify_approval


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
    if len(posts) != 1:
        raise RuntimeError("Exact legacy post was not found uniquely")
    post = posts[0]
    current_title = html.unescape((post.get("title") or {}).get("raw") or "").strip()
    if current_title != payload["expected_current_title"]:
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
    if link.rstrip("/") != payload["expected_new_url"].rstrip("/"):
        raise RuntimeError("Provider returned a URL different from the approved clean URL")
    redirect = session.get(payload["old_url"], allow_redirects=False, timeout=30)
    location = redirect.headers.get("Location", "")
    if redirect.status_code not in {301, 302, 307, 308} or (
        location.rstrip("/") != payload["expected_new_url"].rstrip("/")
    ):
        raise RuntimeError("Old URL did not redirect to the approved clean URL")
    return {"url": link, "old_url": payload["old_url"], "redirect": location}


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
        ))
    print(json.dumps({"updated": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
