#!/usr/bin/env python3
"""Read-only health check for the product's shared Google OAuth connection."""
import os
import sys

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required secret: {name}")
    return value


def error_summary(response):
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        message = error.get("message") or error.get("status")
    else:
        message = error
    return f"HTTP {response.status_code}: {str(message or 'request failed')[:300]}"


def get_json(name, url, headers, params=None, pending_on_403=False):
    response = requests.get(url, headers=headers, params=params, timeout=20)
    if response.ok:
        return response.json()
    prefix = "PENDING" if pending_on_403 and response.status_code in (403, 429) else "FAIL"
    print(f"{prefix} {name}: {error_summary(response)}")
    return None


def main():
    try:
        client_id = required_env("GOOGLE_OAUTH_CLIENT_ID")
        client_secret = required_env("GOOGLE_OAUTH_CLIENT_SECRET")
        refresh_token = required_env("GOOGLE_OAUTH_REFRESH_TOKEN")
    except RuntimeError as exc:
        print(f"FAIL Google OAuth: {exc}")
        return 1

    token_response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if not token_response.ok:
        print(f"FAIL Google token refresh: {error_summary(token_response)}")
        return 1

    access_token = token_response.json().get("access_token")
    if not access_token:
        print("FAIL Google token refresh: access token missing")
        return 1
    print("PASS Google OAuth token refresh")
    headers = {"Authorization": f"Bearer {access_token}"}

    blogger = get_json(
        "Blogger",
        "https://www.googleapis.com/blogger/v3/users/self/blogs",
        headers,
    )
    blogger_ok = blogger is not None
    if blogger_ok:
        blogs = blogger.get("items", [])
        print(f"PASS Blogger: accessible_blogs={len(blogs)}")
        for blog in blogs:
            print(
                "FOUND Blogger: "
                f"name={blog.get('name', '')!r} id={blog.get('id', '')} "
                f"url={blog.get('url', '')}"
            )

    search_console = get_json(
        "Search Console",
        "https://www.googleapis.com/webmasters/v3/sites",
        headers,
    )
    search_console_ok = search_console is not None
    if search_console_ok:
        sites = search_console.get("siteEntry", [])
        print(f"PASS Search Console: accessible_properties={len(sites)}")
        for site in sites:
            print(
                "FOUND Search Console: "
                f"url={site.get('siteUrl', '')} permission={site.get('permissionLevel', '')}"
            )

    analytics = get_json(
        "Google Analytics Admin",
        "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
        headers,
        params={"pageSize": 200},
        pending_on_403=True,
    )
    if analytics is not None:
        summaries = analytics.get("accountSummaries", [])
        properties = [
            prop
            for summary in summaries
            for prop in summary.get("propertySummaries", [])
        ]
        print(f"PASS Google Analytics: accessible_properties={len(properties)}")
        for prop in properties:
            print(
                "FOUND Google Analytics: "
                f"name={prop.get('displayName', '')!r} property={prop.get('property', '')}"
            )

    business = get_json(
        "Google Business Profile",
        "https://mybusinessaccountmanagement.googleapis.com/v1/accounts",
        headers,
        pending_on_403=True,
    )
    if business is not None:
        accounts = business.get("accounts", [])
        print(f"PASS Google Business Profile: accessible_accounts={len(accounts)}")
        for account in accounts:
            print(
                "FOUND Google Business Profile: "
                f"name={account.get('accountName', '')!r} role={account.get('role', '')}"
            )

    return 0 if blogger_ok and search_console_ok else 1


if __name__ == "__main__":
    sys.exit(main())
