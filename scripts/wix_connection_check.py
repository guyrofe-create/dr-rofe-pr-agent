#!/usr/bin/env python3
"""Read-only Wix connection check. Never prints credentials or response bodies."""
import os
import sys

import requests


API_KEY = os.environ.get("WIX_DRGUYROFE_COM_API", "").strip()
SITE_ID = os.environ.get("WIX_DRGUYROFE_COM_SITE_ID", "").strip()
ACCOUNT_ID = os.environ.get("WIX_DRGUYROFE_COM_ACCOUNT_ID", "").strip()
HEADERS = {"Authorization": API_KEY, "wix-site-id": SITE_ID}


def check(name, method, url, **kwargs):
    response = requests.request(method, url, headers=HEADERS, timeout=20, **kwargs)
    if response.ok:
        print(f"PASS {name}: HTTP {response.status_code}")
        return True
    print(f"FAIL {name}: HTTP {response.status_code}")
    return False


def main():
    if not API_KEY or not SITE_ID:
        print("FAIL Wix credentials are missing")
        return 1

    account_headers = {"Authorization": API_KEY, "wix-account-id": ACCOUNT_ID}
    account_ok = False
    if ACCOUNT_ID:
        response = requests.post(
            "https://www.wixapis.com/site-list/v2/sites/query",
            headers=account_headers,
            json={"query": {"filter": {"id": SITE_ID}, "cursorPaging": {"limit": 1}}},
            timeout=20,
        )
        account_ok = response.ok and any(
            site.get("id") == SITE_ID for site in response.json().get("sites", [])
        )
        print(f"{'PASS' if account_ok else 'FAIL'} account owns target site: HTTP {response.status_code}")
    else:
        print("FAIL Wix account ID is missing")

    results = [
        account_ok,
        check(
            "site properties authentication",
            "GET",
            "https://www.wixapis.com/site-properties/v4/properties",
            params={"fields.paths": "businessName"},
        ),
        check(
            "blog read permission",
            "GET",
            "https://www.wixapis.com/v3/posts",
            params={"paging.limit": 1},
        ),
    ]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
