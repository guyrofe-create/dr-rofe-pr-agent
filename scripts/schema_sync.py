#!/usr/bin/env python3
"""
Dr. Guy Rofe - Schema / NAP Sync
Runs weekly on GitHub Actions (see .github/workflows/schema_sync.yml), plus
on-demand via workflow_dispatch.

Single source of truth: data/business_profile.json. This script builds neutral
Person JSON-LD and llms.txt content from that file and pushes it
to every connected WordPress site listed in business_profile.json["sites"],
so every asset stays consistent automatically without manual edits.

A site is skipped (not failed) if its two secrets (username + WP Application
Password) aren't configured yet - same graceful-degradation pattern as every
other module in this repo.
"""
import os
import sys
import json
import base64
import requests

ROOT = os.path.join(os.path.dirname(__file__), "..")
PROFILE_PATH = os.path.join(ROOT, "data", "business_profile.json")
HISTORY_PATH = os.path.join(ROOT, "data", "reputation_history.json")

LOG_LINES = []


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
    schema = {
        "@context": "https://schema.org",
        "@type": "Person",
        "@id": profile["sites"][0]["canonical_url"].rstrip("/") + "/#person",
        "name": profile["name"],
        "alternateName": profile["alternateName"],
        "honorificPrefix": profile["honorificPrefix"],
        "jobTitle": profile["jobTitle"],
        "url": profile["sites"][0]["canonical_url"],
        "image": profile["image"],
        "description": profile["description"],
        "nationality": {"@type": "Country", "name": profile["nationality"]},
        "knowsLanguage": profile["knowsLanguage"],
        "knowsAbout": profile["knowsAbout"],
        "sameAs": profile["sameAs"],
    }
    return schema


def build_llms_txt(profile):
    return f"""```plaintext
# llms.txt

Full name: {profile['name']}
Current role: {profile['jobTitle']}
Professional background: trained physician in obstetrics and gynecology
Current practice status: not currently practicing medicine; not accepting patients; no appointments
Website: [{profile['sites'][0]['canonical_url']}]({profile['sites'][0]['canonical_url']})
Wikidata: {profile['wikidata']}
Languages: Hebrew, English
Official subjects: public medical education, books, articles, podcast and digital products
Keywords: {profile['name']}, Guy Rofe, Guy Rofe MD
```"""


def wp_find_or_create_page(base_url, auth, slug, title):
    resp = requests.get(f"{base_url}/wp-json/wp/v2/pages", auth=auth,
                         params={"slug": slug, "status": "publish,draft"}, timeout=20)
    resp.raise_for_status()
    results = resp.json()
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


def sync_site(site, schema_json_min, llms_content):
    user = env(site["user_env"])
    app_password = env(site["app_password_env"])
    if not user or not app_password:
        log(f"[{site['key']}] SKIPPED - {site['user_env']} / {site['app_password_env']} not set")
        return
    auth = (user, app_password)
    base_url = site["base_url"]
    try:
        schema_page_id = wp_find_or_create_page(
            base_url, auth, site["schema_page_slug"], "Schema Markup — Person / Medical Content Creator"
        )
        wp_update_page(
            base_url,
            auth,
            schema_page_id,
            f'<script type="application/ld+json">{schema_json_min}</script>',
            title="Schema Markup — Person / Medical Content Creator",
        )
        log(f"[{site['key']}] schema-markup page updated (id {schema_page_id})")

        llms_page_id = wp_find_or_create_page(
            base_url, auth, site["llms_page_slug"], "LLMs.txt — AI Search Optimization"
        )
        wp_update_page(
            base_url,
            auth,
            llms_page_id,
            llms_content,
            title="LLMs.txt — AI Search Optimization",
        )
        log(f"[{site['key']}] llms page updated (id {llms_page_id})")
    except requests.exceptions.HTTPError as e:
        log(f"[{site['key']}] ERROR - {e}")
    except Exception as e:
        log(f"[{site['key']}] ERROR - {str(e)}")


def main():
    log("=== Dr. Rofe Schema Sync - Starting ===")
    profile = load_json(PROFILE_PATH, None)
    if not profile:
        log("ERROR: data/business_profile.json not found or invalid - aborting")
        sys.exit(1)

    schema = build_schema(profile)
    schema_json_min = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    llms_content = build_llms_txt(profile)

    for site in profile["sites"]:
        if site.get("platform", "wordpress") != "wordpress":
            api_key = env(site.get("api_key_env", ""))
            site_id = env(site.get("site_id_env", ""))
            if api_key and site_id:
                log(f"[{site['key']}] READY - Wix credentials present; content API sync requires dedicated Wix publisher")
            else:
                log(f"[{site['key']}] SKIPPED - missing {site.get('api_key_env')} / {site.get('site_id_env')}")
            continue
        sync_site(site, schema_json_min, llms_content)

    log("=== Done ===")
    with open("schema_sync_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))


if __name__ == "__main__":
    main()
