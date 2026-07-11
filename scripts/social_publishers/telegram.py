"""Telegram channel publisher via the official Bot API.

Required secrets:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHANNEL_ID   - e.g. "@drguyrofe" or numeric channel id
"""
import requests
from . import common


def is_configured():
    return not common.missing_secrets("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHANNEL_ID")


def publish(title, body, url):
    token = common.env("TELEGRAM_BOT_TOKEN")
    chat_id = common.env("TELEGRAM_CHANNEL_ID")
    text = common.shorten_for_social(title, url, max_len=1000)

    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()["result"]
    return f"https://t.me/{chat_id.lstrip('@')}/{result.get('message_id')}"


def check_token_health():
    if not is_configured():
        return False, "not configured"
    token = common.env("TELEGRAM_BOT_TOKEN")
    try:
        resp = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, resp.json()["result"].get("username", "ok")
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, str(e)
