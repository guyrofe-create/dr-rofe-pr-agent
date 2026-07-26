"""LinkedIn member publishing through the official Share on LinkedIn API."""
import os
from urllib.parse import quote

import requests
from publication_policy import enforce_publication_policy

USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
PUBLISH_URL = "https://api.linkedin.com/v2/ugcPosts"


def _token():
    return os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()


def is_configured():
    return bool(_token())


def _headers():
    return {
        "Authorization": f"Bearer {_token()}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
    }


def current_member():
    if not _token():
        raise RuntimeError("LINKEDIN_ACCESS_TOKEN is not configured")
    response = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    member_id = str(data.get("sub", "")).strip()
    if not member_id:
        raise RuntimeError("LinkedIn userinfo did not return a member identifier")
    return {
        "id": member_id,
        "person_urn": f"urn:li:person:{member_id}",
        "name": data.get("name") or "",
    }


def publish(title, body, url=None):
    member = current_member()
    text = f"{title}\n\n{body}".strip()
    if url:
        text += f"\n\n{url}"
    text = enforce_publication_policy(text)
    payload = {
        "author": member["person_urn"],
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        },
    }
    response = requests.post(PUBLISH_URL, headers=_headers(), json=payload, timeout=30)
    response.raise_for_status()
    post_urn = response.headers.get("x-restli-id", "").strip()
    if not post_urn:
        raise RuntimeError("LinkedIn accepted the post but returned no post identifier")
    return f"https://www.linkedin.com/feed/update/{quote(post_urn, safe=':')}/"
