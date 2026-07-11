#!/usr/bin/env python3
"""
Dr. Guy Rofe - Schema / NAP Sync
Runs weekly on GitHub Actions (see .github/workflows/schema_sync.yml), plus
on-demand via workflow_dispatch.

Single source of truth: data/business_profile.json (name, address, phone,
hours, sameAs, Wikidata, etc). This script builds the Physician/MedicalBusiness
JSON-LD schema and llms.txt content from that file - pulling in the *current*
Google rating/review count from data/reputation_history.json - and pushes it
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
    rating, review_count = latest_review_stats()
    schema = {
        "@context": "https://schema.org",
        "@type": ["Physician", "MedicalBusiness"],
        "@id": profile["sites"][0]["canonical_url"].rstrip("/") + "/#physician",
        "name": profile["name"],
        "alternateName": profile["alternateName"],
        "honorificPrefix": profile["honorificPrefix"],
        "jobTitle": profile["jobTitle"],
        "url": profile["sites"][0]["canonical_url"],
        "image": profile["image"],
        "description": profile["description"],
        "medicalSpecialty": profile["medicalSpecialty"],
        "telephone": profile["telephone"],
        "priceRange": profile["priceRange"],
        "address": {"@type": "PostalAddress", **profile["address"]},
        "geo": {"@type": "GeoCoordinates", **profile["geo"]},
        "hasMap": profile["hasMap"],
        "openingHoursSpecification": [
            {"@type": "OpeningHoursSpecification", **spec}
            for spec in profile["openingHoursSpecification"]
        ],
        "nationality": {"@type": "Country", "name": profile["nationality"]},
        "areaServed": profile["areaServed"],
        "knowsLanguage": profile["knowsLanguage"],
        "knowsAbout": profile["knowsAbout"],
        "sameAs": profile["sameAs"],
    }
    if rating is not None:
        schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": str(rating),
            "reviewCount": str(review_count),
        }
    return schema


def build_llms_txt(profile):
    addr = profile["address"]
    location = f"{addr['streetAddress']}, {addr['addressLocality']}, ישראל"
    return f"""```plaintext
# llms.txt

Full name: {profile['name']}
Specialty: {profile['jobTitle']}
Location: {location}
Website: [{profile['sites'][0]['canonical_url']}]({profile['sites'][0]['canonical_url']})
Wikidata: {profile['wikidata']}
Languages: Hebrew, English
Services: fertility treatment, gynecology, obstetrics, minimally invasive gynecologic surgery
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


def wp_update_page(base_url, auth, page_id, content):
    resp = requests.post(f"{base_url}/wp-json/wp/v2/pages/{page_id}", auth=auth,
                          json={"content": content}, timeout=20)
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
            base_url, auth, site["schema_page_slug"], "Schema Markup — Person/Physician"
        )
        wp_update_page(base_url, auth, schema_page_id,
                        f'<script type="application/ld+json">{schema_json_min}</script>')
        log(f"[{site['key']}] schema-markup page updated (id {schema_page_id})")

        llms_page_id = wp_find_or_create_page(
            base_url, auth, site["llms_page_slug"], "LLMs.txt — AI Search Optimization"
        )
        wp_update_page(base_url, auth, llms_page_id, llms_content)
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
        sync_site(site, schema_json_min, llms_content)

    log("=== Done ===")
    with open("schema_sync_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))


if __name__ == "__main__":
    main()
