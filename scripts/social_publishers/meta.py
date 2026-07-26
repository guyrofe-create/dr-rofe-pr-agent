"""Facebook Page publisher via the Meta Graph API.

Instagram is owner-managed for this pilot and is deliberately blocked here.
Before every Facebook publication, recent Page posts are checked to prevent
duplicates, including posts cross-published from Instagram.

Required secrets:
    FACEBOOK_PAGE_ID       - numeric Page ID
    FACEBOOK_PAGE_TOKEN    - long-lived Page Access Token (Graph API)
"""
import re
import os
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

import requests
from . import common

GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v25.0")
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
INSTAGRAM_MANAGEMENT_MODE = "owner_managed"
FACEBOOK_DUPLICATE_LOOKBACK_POSTS = 50
FACEBOOK_DUPLICATE_TEXT_THRESHOLD = 0.78


class DuplicatePostError(RuntimeError):
    """Raised when a materially similar recent Facebook post already exists."""

    def __init__(self, existing_url=None):
        self.existing_url = existing_url
        detail = f": {existing_url}" if existing_url else ""
        super().__init__(f"SKIPPED_DUPLICATE{detail}")


def facebook_is_configured():
    return not common.missing_secrets("FACEBOOK_PAGE_ID", "FACEBOOK_PAGE_TOKEN")


def instagram_is_configured():
    return False


def _normalize_text(value):
    value = re.sub(r"https?://\S+", " ", value or "", flags=re.IGNORECASE)
    value = re.sub(r"[^\w\u0590-\u05FF]+", " ", value.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def _normalize_url(value):
    if not value:
        return ""
    parsed = urlsplit(value.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.lower() or "https", host, path, "", ""))


def _extract_urls(post):
    urls = set(re.findall(r"https?://[^\s)>\]]+", post.get("message", "")))
    for item in (post.get("attachments") or {}).get("data", []):
        for key in ("unshimmed_url", "url"):
            if item.get(key):
                urls.add(item[key])
        target_url = (item.get("target") or {}).get("url")
        if target_url:
            urls.add(target_url)
    return {_normalize_url(value) for value in urls if value}


def _text_similarity(left, right):
    left_normalized = _normalize_text(left)
    right_normalized = _normalize_text(right)
    if not left_normalized or not right_normalized:
        return 0.0
    sequence_score = SequenceMatcher(
        None, left_normalized, right_normalized
    ).ratio()
    left_words = set(left_normalized.split())
    right_words = set(right_normalized.split())
    union = left_words | right_words
    word_score = len(left_words & right_words) / len(union) if union else 0.0
    return max(sequence_score, word_score)


def find_recent_facebook_duplicate(message, url=None):
    """Return a recent matching Page post, or None.

    A matching canonical URL is always a duplicate. Text-only Instagram
    cross-posts are caught by normalized Hebrew text similarity.
    """
    page_id = common.env("FACEBOOK_PAGE_ID")
    token = common.env("FACEBOOK_PAGE_TOKEN")
    response = requests.get(
        f"{GRAPH}/{page_id}/published_posts",
        params={
            "fields": (
                "id,message,created_time,permalink_url,"
                "attachments{unshimmed_url,url,target}"
            ),
            "limit": FACEBOOK_DUPLICATE_LOOKBACK_POSTS,
            "access_token": token,
        },
        timeout=20,
    )
    response.raise_for_status()
    candidate_url = _normalize_url(url)
    candidate_is_homepage = (
        bool(candidate_url) and urlsplit(candidate_url).path in ("", "/")
    )
    for post in response.json().get("data", []):
        if (
            candidate_url
            and not candidate_is_homepage
            and candidate_url in _extract_urls(post)
        ):
            return post
        if (
            _text_similarity(message, post.get("message", ""))
            >= FACEBOOK_DUPLICATE_TEXT_THRESHOLD
        ):
            return post
    return None


def check_recent_posts_access():
    """Confirm the token can read Page posts required by duplicate protection."""
    page_id = common.env("FACEBOOK_PAGE_ID")
    token = common.env("FACEBOOK_PAGE_TOKEN")
    if not page_id or not token:
        return False, "not configured"
    try:
        response = requests.get(
            f"{GRAPH}/{page_id}/published_posts",
            params={
                "fields": "id,message,created_time,permalink_url",
                "limit": 1,
                "access_token": token,
            },
            timeout=15,
        )
        if response.status_code != 200:
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
        count = len(response.json().get("data", []))
        return True, f"read access confirmed ({count} recent post returned)"
    except Exception as exc:
        return False, str(exc)


def publish_facebook(title, body, url, image_url=None, alt_text=None):
    page_id = common.env("FACEBOOK_PAGE_ID")
    token = common.env("FACEBOOK_PAGE_TOKEN")
    message = common.shorten_for_social(title, url, max_len=1800, body=body)
    duplicate = find_recent_facebook_duplicate(message, url)
    if duplicate:
        raise DuplicatePostError(
            duplicate.get("permalink_url")
            or (
                f"https://www.facebook.com/{duplicate['id']}"
                if duplicate.get("id")
                else None
            )
        )

    if image_url:
        payload = {
            "caption": message,
            "url": image_url,
            "published": "true",
            "access_token": token,
        }
        if alt_text:
            payload["alt_text_custom"] = alt_text
        endpoint = f"{GRAPH}/{page_id}/photos"
    else:
        payload = {"message": message, "access_token": token}
        if url:
            payload["link"] = url
        endpoint = f"{GRAPH}/{page_id}/feed"

    resp = requests.post(endpoint, data=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    post_id = result.get("id")
    return f"https://www.facebook.com/{post_id}" if post_id else str(result)


def publish_instagram(title, body, url, image_url):
    raise RuntimeError(
        "Instagram publishing is disabled: this pilot account is owner-managed"
    )


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
