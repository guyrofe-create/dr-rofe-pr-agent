"""Google Business Profile information-post publisher.

The publisher is intentionally limited to STANDARD informational posts with:
* an exact approved Hebrew summary;
* one public HTTPS image URL;
* a LEARN_MORE link to the exact approved canonical article.

It never edits business details, hours, services, booking links, or availability.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publication_policy import enforce_publication_policy
from . import common, google_oauth


ACCOUNTS_URL = "https://mybusinessaccountmanagement.googleapis.com/v1/accounts"
MY_BUSINESS_V4 = "https://mybusiness.googleapis.com/v4"
MAX_SUMMARY_LENGTH = 700
APPROVED_CONTENT_HOSTS = frozenset(
    {
        "guyrofe.com",
        "www.guyrofe.com",
        "drguyrofe.co.il",
        "www.drguyrofe.co.il",
        "drguyrofe.com",
        "www.drguyrofe.com",
    }
)


def is_configured() -> bool:
    return not common.missing_secrets(
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    )


def _access_token() -> str:
    return google_oauth.refresh_access_token(session=requests)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-GOOG-API-FORMAT-VERSION": "2",
    }


def _resource(prefix: str, value: str | None) -> str | None:
    item = str(value or "").strip().strip("/")
    if not item:
        return None
    return item if item.startswith(f"{prefix}/") else f"{prefix}/{item}"


def _configured_location() -> tuple[str | None, str | None]:
    account = _resource("accounts", common.env("GOOGLE_BUSINESS_ACCOUNT_ID"))
    location_value = str(common.env("GOOGLE_BUSINESS_LOCATION_ID") or "").strip()
    if location_value.startswith("accounts/"):
        parts = location_value.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "accounts" and parts[2] == "locations":
            return f"accounts/{parts[1]}", location_value.strip("/")
        raise ValueError("GOOGLE_BUSINESS_LOCATION_ID has an invalid resource name")
    location = _resource("locations", location_value)
    if bool(account) != bool(location):
        raise RuntimeError(
            "Set both GOOGLE_BUSINESS_ACCOUNT_ID and "
            "GOOGLE_BUSINESS_LOCATION_ID, or leave both empty for safe discovery"
        )
    if account and location:
        return account, f"{account}/{location}"
    return None, None


def list_accounts(token: str) -> list[dict]:
    response = requests.get(ACCOUNTS_URL, headers=_headers(token), timeout=20)
    response.raise_for_status()
    return list(response.json().get("accounts") or [])


def list_locations(token: str, account_name: str) -> list[dict]:
    response = requests.get(
        f"{MY_BUSINESS_V4}/{account_name}/locations",
        headers=_headers(token),
        params={"pageSize": 100},
        timeout=30,
    )
    response.raise_for_status()
    return list(response.json().get("locations") or [])


def resolve_location(token: str) -> tuple[str, str, dict]:
    """Resolve safely: explicit IDs, or automatic discovery only when unique."""
    configured_account, configured_location = _configured_location()
    if configured_account and configured_location:
        return configured_account, configured_location, {
            "name": configured_location,
            "locationName": "configured location",
        }

    candidates: list[tuple[str, str, dict]] = []
    for account in list_accounts(token):
        account_name = str(account.get("name") or "").strip()
        if not account_name:
            continue
        for location in list_locations(token, account_name):
            raw_name = str(location.get("name") or "").strip()
            if not raw_name:
                continue
            location_name = (
                raw_name
                if raw_name.startswith("accounts/")
                else f"{account_name}/{_resource('locations', raw_name)}"
            )
            candidates.append((account_name, location_name, location))
    if not candidates:
        raise RuntimeError("Google Business Profile returned no accessible locations")
    if len(candidates) != 1:
        names = ", ".join(
            str(item[2].get("locationName") or item[1]) for item in candidates[:8]
        )
        raise RuntimeError(
            "Multiple Google Business locations are accessible; configure exact "
            "GOOGLE_BUSINESS_ACCOUNT_ID and GOOGLE_BUSINESS_LOCATION_ID. "
            f"Found: {names}"
        )
    return candidates[0]


def _validate_public_https_url(value: str, field: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{field} must be a public HTTPS URL")
    return url


def _validate_content_link(value: str) -> str:
    url = _validate_public_https_url(value, "Google Business link")
    parsed = urlparse(url)
    if parsed.hostname not in APPROVED_CONTENT_HOSTS:
        raise ValueError("Google Business link must use an approved official site")
    if parsed.path.rstrip("/") == "":
        raise ValueError(
            "Google Business link must target the exact topic page, not a homepage"
        )
    return url


def _post_payload(
    summary: str,
    link: str,
    image_url: str,
    *,
    language_code: str = "he",
) -> dict:
    text = enforce_publication_policy(summary)
    if not text:
        raise ValueError("Google Business summary is empty")
    if len(text) > MAX_SUMMARY_LENGTH:
        raise ValueError(
            f"Google Business summary exceeds {MAX_SUMMARY_LENGTH} characters"
        )
    return {
        "languageCode": language_code,
        "summary": text,
        "topicType": "STANDARD",
        "callToAction": {
            "actionType": "LEARN_MORE",
            "url": _validate_content_link(link),
        },
        "media": [
            {
                "mediaFormat": "PHOTO",
                "sourceUrl": _validate_public_https_url(
                    image_url, "Google Business image"
                ),
            }
        ],
    }


def _existing_post(token: str, location_name: str, payload: dict) -> dict | None:
    response = requests.get(
        f"{MY_BUSINESS_V4}/{location_name}/localPosts",
        headers=_headers(token),
        params={"pageSize": 100},
        timeout=30,
    )
    response.raise_for_status()
    for post in response.json().get("localPosts") or []:
        if (
            post.get("summary") == payload["summary"]
            and (post.get("callToAction") or {}).get("url")
            == payload["callToAction"]["url"]
        ):
            return post
    return None


def _receipt(post: dict, *, account: str, location: str) -> dict:
    search_url = str(post.get("searchUrl") or "").strip()
    if not search_url:
        raise RuntimeError(
            "Google accepted the post but returned no searchUrl; "
            "manual reconciliation is required"
        )
    return {
        "url": search_url,
        "provider_receipt": {
            "name": post.get("name"),
            "state": post.get("state"),
            "createTime": post.get("createTime"),
            "searchUrl": search_url,
            "account": account,
            "location": location,
        },
    }


def publish(
    summary: str,
    link: str,
    image_url: str,
    *,
    language_code: str = "he",
    access_token: str | None = None,
) -> dict:
    token = access_token or _access_token()
    account, location, _metadata = resolve_location(token)
    payload = _post_payload(
        summary,
        link,
        image_url,
        language_code=language_code,
    )
    existing = _existing_post(token, location, payload)
    if existing:
        return _receipt(existing, account=account, location=location)

    response = requests.post(
        f"{MY_BUSINESS_V4}/{location}/localPosts",
        headers=_headers(token),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    post = response.json()
    if not post.get("searchUrl") and post.get("name"):
        # Google can briefly return PROCESSING before the public link is populated.
        for _attempt in range(3):
            time.sleep(2)
            check = requests.get(
                f"{MY_BUSINESS_V4}/{post['name']}",
                headers=_headers(token),
                timeout=20,
            )
            check.raise_for_status()
            post = check.json()
            if post.get("searchUrl"):
                break
    return _receipt(post, account=account, location=location)


def reconcile(
    summary: str,
    link: str,
    image_url: str,
    *,
    language_code: str = "he",
    access_token: str | None = None,
) -> dict | None:
    """Return the matching live post, or prove that the approved post is absent."""
    token = access_token or _access_token()
    account, location, _metadata = resolve_location(token)
    payload = _post_payload(
        summary,
        link,
        image_url,
        language_code=language_code,
    )
    existing = _existing_post(token, location, payload)
    if existing is None:
        return None
    return _receipt(existing, account=account, location=location)


def check_connection() -> dict:
    token = _access_token()
    account, location, metadata = resolve_location(token)
    return {
        "account": account,
        "location": location,
        "location_name": metadata.get("locationName") or metadata.get("title") or "",
    }
