"""Facebook Page + Instagram Business publisher via the Meta Graph API.

Both platforms share one Meta developer app and one Page Access Token,
because an Instagram Business account must be linked to a Facebook Page.

Required secrets:
    FACEBOOK_PAGE_ID       - numeric Page ID
    FACEBOOK_PAGE_TOKEN    - long-lived Page Access Token (Graph API)
    INSTAGRAM_BUSINESS_ID  - IG Business Account ID linked to the page (optional,
                             only needed if you also want IG auto-posting)
"""
import os
import requests
from . import common

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"


def facebook_is_configured():
    return not common.missing_secrets("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN")


def instagram_is_configured():
    return not common.missing_secrets("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN")


def resolve_instagram_business_id():
    """Return the configured IG ID or discover the account linked to the Page."""
    configured = common.env("INSTAGRAM_BUSINESS_ID")
    if configured:
        return configured
    page_id = common.env("FACEBOOK_PAGE_ID")
    token = common.env("FACEBOOK_PAGE_TOKEN")
    resp = requests.get(
        f"{GRAPH}/{page_id}",
        params={"fields": "instagram_business_account{id,username}", "access_token": token},
        timeout=15,
    )
    resp.raise_for_status()
    account = resp.json().get("instagram_business_account") or {}
    if not account.get("id"):
        raise RuntimeError("No Instagram Business account is linked to the Facebook Page")
    return account["id"]


def publish_facebook(title, body, url, image_url=None):
    page_id = common.env("FACEBOOK_PAGE_ID")
    token = common.env("FACEBOOK_PAGE_TOKEN")
    message = common.shorten_for_social(title, url, max_len=1800)

    payload = {"message": message, "access_token": token}
    if url:
        payload["link"] = url

    resp = requests.post(f"{GRAPH}/{page_id}/feed", data=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    post_id = result.get("id")
    return f"https://www.facebook.com/{post_id}" if post_id else str(result)


def publish_instagram(title, body, url, image_url):
    """IG posting requires an image/video container. `image_url` is required
    (IG has no pure-text post type)."""
    if not image_url:
        raise ValueError("Instagram requires image_url (no text-only posts on IG)")

    ig_id = resolve_instagram_business_id()
    token = common.env("FACEBOOK_PAGE_TOKEN")
    caption = common.shorten_for_social(title, url, max_len=2000)

    # Step 1: create media container
    resp = requests.post(
        f"{GRAPH}/{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    creation_id = resp.json()["id"]

    # Step 2: publish container
    resp = requests.post(
        f"{GRAPH}/{ig_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    resp.raise_for_status()
    media_id = resp.json().get("id")
    return f"https://www.instagram.com/p/{media_id}" if media_id else str(resp.json())


def check_token_health():
    """Returns (ok: bool, detail: str) using the Graph API debug_token-free
    lightweight call (fetch page name)."""
    page_id = common.env("FACEBOOK_PAGE_ID")
    token = common.env("FACEBOOK_PAGE_TOKEN")
    if not page_id or not token:
        return False, "not configured"
    try:
        resp = requests.get(
            f"{GRAPH}/{page_id}", params={"fields": "name", "access_token": token}, timeout=15
        )
        if resp.status_code == 200:
            return True, resp.json().get("name", "ok")
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
