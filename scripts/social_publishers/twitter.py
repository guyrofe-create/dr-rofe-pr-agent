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


def is_configured():
    return not common.missing_secrets(
        "TWITTER_API_KEY", "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
    )


def publish(title, body, url):
    text = common.shorten_for_social(title, url, max_len=270)
    header = common.oauth1_header(
        "POST", TWEETS_URL, {},
        common.env("TWITTER_API_KEY"), common.env("TWITTER_API_SECRET"),
        common.env("TWITTER_ACCESS_TOKEN"), common.env("TWITTER_ACCESS_SECRET"),
    )
    resp = requests.post(
        TWEETS_URL,
        headers={"Authorization": header, "Content-Type": "application/json"},
        json={"text": text},
        timeout=30,
    )
    resp.raise_for_status()
    tweet_id = resp.json()["data"]["id"]
    return f"https://x.com/GuyRofe/status/{tweet_id}"


def check_token_health():
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
