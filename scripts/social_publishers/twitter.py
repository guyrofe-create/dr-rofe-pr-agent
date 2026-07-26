"""Twitter/X publisher via API v2 (OAuth 1.0a user context).

Required secrets:
    TWITTER_API_KEY
    TWITTER_API_SECRET
    TWITTER_ACCESS_TOKEN
    TWITTER_ACCESS_SECRET
"""
import requests
from . import common

TWEETS_URL = "https://api.twitter.com/2/tweets"
MEDIA_UPLOAD_URL = "https://upload.twitter.com/1.1/media/upload.json"
MEDIA_METADATA_URL = "https://upload.twitter.com/1.1/media/metadata/create.json"


def publishing_enabled():
    """X stays disabled until the suspended account is restored legitimately."""
    return (common.env("X_PUBLISHING_ENABLED") or "").lower() == "true"


def credentials_configured():
    return not common.missing_secrets(
        "TWITTER_API_KEY", "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
    )


def is_configured():
    return publishing_enabled() and credentials_configured()


def _oauth_header(method, endpoint):
    return common.oauth1_header(
        method,
        endpoint,
        {},
        common.env("TWITTER_API_KEY"),
        common.env("TWITTER_API_SECRET"),
        common.env("TWITTER_ACCESS_TOKEN"),
        common.env("TWITTER_ACCESS_SECRET"),
    )


def _upload_image(image_url, alt_text=None):
    image = requests.get(image_url, timeout=30)
    image.raise_for_status()
    response = requests.post(
        MEDIA_UPLOAD_URL,
        headers={"Authorization": _oauth_header("POST", MEDIA_UPLOAD_URL)},
        files={"media": ("social-image.png", image.content, "image/png")},
        timeout=60,
    )
    response.raise_for_status()
    media_id = response.json()["media_id_string"]
    if alt_text:
        metadata = requests.post(
            MEDIA_METADATA_URL,
            headers={
                "Authorization": _oauth_header("POST", MEDIA_METADATA_URL),
                "Content-Type": "application/json",
            },
            json={"media_id": media_id, "alt_text": {"text": alt_text[:1000]}},
            timeout=30,
        )
        metadata.raise_for_status()
    return media_id


def publish(title, body, url, image_url=None, alt_text=None):
    if not publishing_enabled():
        raise RuntimeError(
            "X publishing is disabled by owner policy pending account restoration"
        )
    if not credentials_configured():
        raise RuntimeError("X publishing credentials are not configured")
    text = common.shorten_for_social(title, url, max_len=270, body=body)
    header = common.oauth1_header(
        "POST", TWEETS_URL, {},
        common.env("TWITTER_API_KEY"), common.env("TWITTER_API_SECRET"),
        common.env("TWITTER_ACCESS_TOKEN"), common.env("TWITTER_ACCESS_SECRET"),
    )
    payload = {"text": text}
    if image_url:
        payload["media"] = {"media_ids": [_upload_image(image_url, alt_text)]}
    resp = requests.post(
        TWEETS_URL,
        headers={"Authorization": header, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    tweet_id = resp.json()["data"]["id"]
    return f"https://x.com/GuyRofe/status/{tweet_id}"


def check_token_health():
    if credentials_configured() and not publishing_enabled():
        return True, "publishing disabled by owner policy"
    if not is_configured():
        return False, "not configured"
    header = common.oauth1_header(
        "GET", "https://api.twitter.com/2/users/me", {},
        common.env("TWITTER_API_KEY"), common.env("TWITTER_API_SECRET"),
        common.env("TWITTER_ACCESS_TOKEN"), common.env("TWITTER_ACCESS_SECRET"),
    )
    try:
        resp = requests.get(
            "https://api.twitter.com/2/users/me",
            headers={"Authorization": header}, timeout=15,
        )
        if resp.status_code == 200:
            return True, resp.json().get("data", {}).get("username", "ok")
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
