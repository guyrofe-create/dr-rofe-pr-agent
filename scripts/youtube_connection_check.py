#!/usr/bin/env python3
"""Read-only YouTube OAuth connection check; never prints credentials."""
import os
import sys

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required secret: {name}")
    return value


def safe_error(response):
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    if isinstance(error, dict):
        message = error.get("message") or error.get("status")
    else:
        message = error
    return f"HTTP {response.status_code}: {str(message or 'request failed')[:240]}"


def main():
    try:
        client_id = required_env("YOUTUBE_CLIENT_ID")
        client_secret = required_env("YOUTUBE_CLIENT_SECRET")
        refresh_token = required_env("YOUTUBE_REFRESH_TOKEN")
    except RuntimeError as exc:
        print(f"FAIL YouTube OAuth: {exc}")
        return 1

    token_response = requests.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if not token_response.ok:
        print(f"FAIL YouTube token refresh: {safe_error(token_response)}")
        return 1

    access_token = token_response.json().get("access_token")
    if not access_token:
        print("FAIL YouTube token refresh: access token missing")
        return 1

    channel_response = requests.get(
        CHANNELS_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"part": "id,snippet", "mine": "true"},
        timeout=20,
    )
    if not channel_response.ok:
        print(f"FAIL YouTube channel lookup: {safe_error(channel_response)}")
        return 1

    channels = channel_response.json().get("items", [])
    if len(channels) != 1:
        print(f"FAIL YouTube channel lookup: expected 1 channel, received {len(channels)}")
        return 1

    channel = channels[0]
    channel_id = channel.get("id", "")
    snippet = channel.get("snippet", {})
    title = snippet.get("title", "")
    custom_url = snippet.get("customUrl", "")
    expected_id = os.environ.get("YOUTUBE_CHANNEL_ID", "").strip()

    print(f"PASS YouTube OAuth: channel_title={title!r}")
    print(f"PASS YouTube OAuth: channel_id={channel_id}")
    if custom_url:
        print(f"PASS YouTube OAuth: custom_url={custom_url}")

    if expected_id and channel_id != expected_id:
        print(
            "FAIL YouTube target mismatch: "
            f"expected_channel_id={expected_id}, connected_channel_id={channel_id}"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
