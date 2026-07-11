"""Blogger publisher via Google Blogger API v3 (OAuth2 refresh token).

Required secrets:
    GOOGLE_OAUTH_CLIENT_ID
    GOOGLE_OAUTH_CLIENT_SECRET
    GOOGLE_OAUTH_REFRESH_TOKEN   - obtained once via Google OAuth Playground
    BLOGGER_BLOG_ID              - numeric blog ID (from Blogger dashboard)
"""
import requests
from . import common

TOKEN_URL = "https://oauth2.googleapis.com/token"


def is_configured():
    return not common.missing_secrets(
        "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN", "BLOGGER_BLOG_ID",
    )


def _access_token():
    resp = requests.post(TOKEN_URL, data={
        "client_id": common.env("GOOGLE_OAUTH_CLIENT_ID"),
        "client_secret": common.env("GOOGLE_OAUTH_CLIENT_SECRET"),
        "refresh_token": common.env("GOOGLE_OAUTH_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }, timeout=20)
    resp.raise_for_status()
    return resp.json()["access_token"]


def publish(title, body_html, url=None):
    blog_id = common.env("BLOGGER_BLOG_ID")
    token = _access_token()
    content = body_html
    if url:
        content += f'<p><a href="{url}">קריאה מלאה באתר</a></p>'

    resp = requests.post(
        f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/posts/",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "content": content},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("url", "published")


def check_token_health():
    if not is_configured():
        return False, "not configured"
    try:
        token = _access_token()
        blog_id = common.env("BLOGGER_BLOG_ID")
        resp = requests.get(
            f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        if resp.status_code == 200:
            return True, resp.json().get("name", "ok")
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
