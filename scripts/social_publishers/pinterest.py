"""Pinterest publisher via Pinterest API v5.

Required secrets:
    PINTEREST_ACCESS_TOKEN
    PINTEREST_BOARD_ID
"""
import requests
from . import common


def is_configured():
    return not common.missing_secrets("PINTEREST_ACCESS_TOKEN", "PINTEREST_BOARD_ID")


def publish(title, body, url, image_url):
    if not image_url:
        raise ValueError("Pinterest requires image_url (pins must have an image)")

    token = common.env("PINTEREST_ACCESS_TOKEN")
    board_id = common.env("PINTEREST_BOARD_ID")
    description = common.shorten_for_social(title, url, max_len=500)

    resp = requests.post(
        "https://api.pinterest.com/v5/pins",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "board_id": board_id,
            "title": title[:100],
            "description": description,
            "link": url,
            "media_source": {"source_type": "image_url", "url": image_url},
        },
        timeout=30,
    )
    resp.raise_for_status()
    pin_id = resp.json().get("id")
    return f"https://www.pinterest.com/pin/{pin_id}" if pin_id else str(resp.json())


def check_token_health():
    if not is_configured():
        return False, "not configured"
    token = common.env("PINTEREST_ACCESS_TOKEN")
    try:
        resp = requests.get(
            "https://api.pinterest.com/v5/user_account",
            headers={"Authorization": f"Bearer {token}"}, timeout=15,
        )
        if resp.status_code == 200:
            return True, resp.json().get("username", "ok")
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
