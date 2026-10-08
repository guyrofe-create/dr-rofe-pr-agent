#!/usr/bin/env python3
"""
Single-tenant Schema / NAP Sync
Runs weekly on GitHub Actions (see .github/workflows/schema_sync.yml), plus
on-demand via workflow_dispatch.

Single source of truth: data/business_profile.json. This script builds and,
only after exact approval, publishes a ProfilePage/Person graph to connected
WordPress sites. It does not create or update llms.txt pages: Google does not
require them and existing public pages need separate deletion approval.

A site is skipped (not failed) if its two secrets (username + WP Application
Password) aren't configured yet - same graceful-degradation pattern as every
other module in this repo.
"""
import os
import sys
import json
import base64
import requests
from reputation_core.installation import data_path
from reputation_core.entity_seo import (
    build_profile_page_schema,
    render_profile_page,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROFILE_PATH = data_path("business_profile.json")
HISTORY_PATH = data_path("reputation_history.json")

LOG_LINES = []
RESULT_PATH = "schema_sync_result.json"


def log(msg):
    print(msg)
    LOG_LINES.append(msg)


def env(name):
    return os.environ.get(name, "").strip() or None


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def latest_review_stats():
    history = load_json(HISTORY_PATH, {"snapshots": []})
    for snap in reversed(history.get("snapshots", [])):
        rv = snap.get("reviews") or {}
        if rv.get("status") == "ok" and rv.get("rating") is not None:
            return rv.get("rating"), rv.get("total_reviews")
    return None, None


def build_schema(profile):
    return build_profile_page_schema(profile)


def llms_txt_policy():
    return {
        "status": "deprecated_not_published",
        "reason": "Google recommends foundational SEO instead of unnecessary llms.txt files.",
        "existing_public_page_action": "separate_exact_approval_required_for_removal_or_noindex",
    }


def wp_find_or_create_page(base_url, auth, slug, title):
    resp = requests.get(f"{base_url}/wp-json/wp/v2/pages", auth=auth,
                         params={"slug": slug, "status": "publish"}, timeout=20)
    resp.raise_for_status()
    try:
        results = resp.json()
    except ValueError as exc:
        content_type = resp.headers.get("content-type", "unknown")
        raise RuntimeError(
            "WordPress page lookup returned non-JSON "
            f"(HTTP {resp.status_code}, content-type {content_type}, "
            f"{len(resp.content)} bytes)"
        ) from exc
    if results:
        return results[0]["id"]
    # doesn't exist yet - create it
    resp = requests.post(f"{base_url}/wp-json/wp/v2/pages", auth=auth,
                          json={"title": title, "slug": slug, "status": "publish", "content": ""},
                          timeout=20)
    resp.raise_for_status()
    return resp.json()["id"]


def wp_update_page(base_url, auth, page_id, content, title=None):
    payload = {"content": content}
    if title:
        payload["title"] = title
    resp = requests.post(f"{base_url}/wp-json/wp/v2/pages/{page_id}", auth=auth,
                          json=payload, timeout=20)
    resp.raise_for_status()
    return resp.json()


def sync_site(site, profile):
    user = env(site["user_env"])
    app_password = env(site["app_password_env"])
    if not user or not app_password:
        log(f"[{site['key']}] SKIPPED - {site['user_env']} / {site['app_password_env']} not set")
        return {"site_key": site["key"], "status": "skipped_missing_credentials"}
    auth = (user, app_password)
    base_url = site["base_url"]
    slug = site.get("profile_page_slug", "profile")
    page_url = f"{base_url.rstrip('/')}/{slug}/"
    profile_content = render_profile_page(profile, page_url=page_url)
    try:
        schema_page_id = wp_find_or_create_page(
            base_url,
            auth,
            slug,
            f"{profile['name']} — פרופיל רשמי",
        )
        wp_update_page(
            base_url,
            auth,
            schema_page_id,
            profile_content,
            title=f"{profile['name']} — פרופיל רשמי",
        )
        log(f"[{site['key']}] ProfilePage/Person page updated (id {schema_page_id})")
        return {"site_key": site["key"], "status": "applied", "profile_page_id": schema_page_id}
    except requests.exceptions.HTTPError as e:
        log(f"[{site['key']}] ERROR - {e}")
        return {"site_key": site["key"], "status": "error", "error_type": type(e).__name__}
    except Exception as e:
        log(f"[{site['key']}] ERROR - {str(e)}")
        return {"site_key": site["key"], "status": "error", "error_type": type(e).__name__}


def write_outputs(result):
    with open("schema_sync_log.txt", "w", encoding="utf-8") as handle:
        handle.write("\n".join(LOG_LINES))
    with open(RESULT_PATH, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    log("=== Single-tenant Schema Sync - Starting ===")
    profile = load_json(PROFILE_PATH, None)
    if not profile:
        log("ERROR: data/business_profile.json not found or invalid - aborting")
        sys.exit(1)

    schema = build_schema(profile)
    schema_json_min = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    publish_approved = env("ENTITY_SYNC_APPROVED") == "true"
    result = {
        "mode": "apply" if publish_approved else "audit_only",
        "status": "pending" if publish_approved else "audit_only",
        "public_write_performed": False,
        "profile_preview_bytes": len(schema_json_min),
        "llms_txt": llms_txt_policy(),
        "sites": [],
    }
    log(f"ProfilePage preview generated ({len(schema_json_min)} bytes)")
    if not publish_approved:
        log("AUDIT ONLY - ENTITY_SYNC_APPROVED=true was not supplied; no public pages changed")
        write_outputs(result)
        return

    for site in profile["sites"]:
        if site.get("public_sync_prohibited"):
            log(
                f"[{site['key']}] SKIPPED - public sync prohibited; "
                "read-only audit only until separate exact approval"
            )
            result["sites"].append({"site_key": site["key"], "status": "skipped_write_protected"})
            continue
        if site.get("platform", "wordpress") != "wordpress":
            api_key = env(site.get("api_key_env", ""))
            site_id = env(site.get("site_id_env", ""))
            if api_key and site_id:
                log(f"[{site['key']}] READY - Wix credentials present; content API sync requires dedicated Wix publisher")
                result["sites"].append({"site_key": site["key"], "status": "ready_requires_dedicated_publisher"})
            else:
                log(f"[{site['key']}] SKIPPED - missing {site.get('api_key_env')} / {site.get('site_id_env')}")
                result["sites"].append({"site_key": site["key"], "status": "skipped_missing_credentials"})
            continue
        site_result = sync_site(site, profile)
        result["sites"].append(site_result)
        if site_result.get("status") == "applied":
            result["public_write_performed"] = True

    log("=== Done ===")
    result["status"] = "applied" if result["public_write_performed"] else "no_public_write"
    if any(item.get("status") == "error" for item in result["sites"]):
        result["status"] = "completed_with_errors"
    write_outputs(result)
    if result["status"] == "completed_with_errors":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
