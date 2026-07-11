"""Shared helpers for all platform publishers."""
import os
import time
import hmac
import hashlib
import base64
import random
import string
import urllib.parse


def env(name):
    return os.environ.get(name, "").strip() or None


def missing_secrets(*names):
    """Return the list of env var names that are not set."""
    return [n for n in names if not env(n)]


# ─── Minimal OAuth 1.0a signer (used by Twitter/X and Tumblr) ────────────────

def oauth1_header(method, url, params, consumer_key, consumer_secret,
                   token, token_secret, extra_oauth=None):
    """Build an OAuth 1.0a 'Authorization' header value (HMAC-SHA1)."""
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": "".join(random.choices(string.ascii_letters + string.digits, k=32)),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    if extra_oauth:
        oauth_params.update(extra_oauth)

    all_params = {**params, **oauth_params}
    base_str = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(all_params[k]), safe='')}"
        for k in sorted(all_params)
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(base_str, safe=""),
    ])
    signing_key = f"{urllib.parse.quote(consumer_secret, safe='')}&{urllib.parse.quote(token_secret, safe='')}"
    signature = base64.b64encode(
        hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    ).decode()
    oauth_params["oauth_signature"] = signature

    header = "OAuth " + ", ".join(
        f'{urllib.parse.quote(k, safe="")}="{urllib.parse.quote(v, safe="")}"'
        for k, v in sorted(oauth_params.items())
    )
    return header


def shorten_for_social(title, url, max_len=250):
    """Build a short social caption from an article title + link."""
    suffix = f"\n\nקריאה מלאה: {url}" if url else ""
    room = max_len - len(suffix)
    text = title if len(title) <= room else title[: room - 1].rstrip() + "…"
    return text + suffix
