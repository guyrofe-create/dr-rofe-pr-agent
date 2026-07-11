"""Tumblr publisher via API v2 (OAuth 1.0a).

Required secrets:
    TUMBLR_CONSUMER_KEY
    TUMBLR_CONSUMER_SECRET
    TUMBLR_OAUTH_TOKEN
    TUMBLR_OAUTH_SECRET
    TUMBLR_BLOG_NAME     - e.g. "drguyrofe" (from drguyrofe.tumblr.com)
"""
import requests
from . import common


def is_configured():
    return not common.missing_secrets(
        "TUMBLR_CONSUMER_KEY", "TUMBLR_CONSUMER_SECRET",
        "TUMBLR_OAUTH_TOKEN", "TUMBLR_OAUTH_SECRET", "TUMBLR_BLOG_NAME",
    )


def _post_url():
    blog = common.env("TUMBLR_BLOG_NAME")
    return f"https://api.tumblr.com/v2/blog/{blog}.tumblr.com/posts"


def publish(title, body, url):
    post_url = _post_url()
    params = {"type": "text", "title": title, "body": body}
    if url:
        params["body"] += f'\n\n<a href="{url}">קריאה מלאה באתר</a>'

    header = common.oauth1_header(
        "POST", post_url, params,
        common.env("TUMBLR_CONSUMER_KEY"), common.env("TUMBLR_CONSUMER_SECRET"),
        common.env("TUMBLR_OAUTH_TOKEN"), common.env("TUMBLR_OAUTH_SECRET"),
    )
    resp = requests.post(
        post_url, data=params,
        headers={"Authorization": header},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    post_id = result.get("response", {}).get("id")
    blog = common.env("TUMBLR_BLOG_NAME")
    return f"https://{blog}.tumblr.com/post/{post_id}" if post_id else str(result)


def check_token_health():
    if not is_configured():
        return False, "not configured"
    blog = common.env("TUMBLR_BLOG_NAME")
    info_url = f"https://api.tumblr.com/v2/blog/{blog}.tumblr.com/info"
    try:
        resp = requests.get(info_url, params={"api_key": common.env("TUMBLR_CONSUMER_KEY")}, timeout=15)
        if resp.status_code == 200:
            return True, "ok"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
