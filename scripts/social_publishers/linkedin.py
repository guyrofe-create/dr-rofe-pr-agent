"""LinkedIn member publishing through the official Share on LinkedIn API."""
import os
from urllib.parse import quote

import requests
from publication_policy import enforce_publication_policy

USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
PUBLISH_URL = "https://api.linkedin.com/v2/ugcPosts"
REGISTER_UPLOAD_URL = "https://api.linkedin.com/v2/assets?action=registerUpload"


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


def _upload_image(owner_urn, image_bytes):
    response = requests.post(
        REGISTER_UPLOAD_URL,
        headers=_headers(),
        json={
            "registerUploadRequest": {
                "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
                "owner": owner_urn,
                "serviceRelationships": [
                    {
                        "relationshipType": "OWNER",
                        "identifier": "urn:li:userGeneratedContent",
                    }
                ],
                "supportedUploadMechanism": ["SYNCHRONOUS_UPLOAD"],
            }
        },
        timeout=30,
    )
    response.raise_for_status()
    value = response.json()["value"]
    mechanism = value["uploadMechanism"][
        "com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"
    ]
    upload = requests.put(
        mechanism["uploadUrl"],
        headers={
            "Authorization": f"Bearer {_token()}",
            "Content-Type": "image/png",
        },
        data=image_bytes,
        timeout=60,
    )
    upload.raise_for_status()
    return value["asset"]


def publish(
    title,
    body,
    url=None,
    image_bytes=None,
    alt_text=None,
    disclosure=None,
):
    member = current_member()
    text = f"{title}\n\n{body}".strip()
    if url:
        text += f"\n\n{url}"
    if disclosure:
        text += f"\n\n{disclosure.strip()}"
    text = enforce_publication_policy(text)
    share_content = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": "NONE",
    }
    if image_bytes:
        share_content.update(
            {
                "shareMediaCategory": "IMAGE",
                "media": [
                    {
                        "status": "READY",
                        "media": _upload_image(member["person_urn"], image_bytes),
                        "description": {"text": (alt_text or title)[:300]},
                        "title": {"text": title[:200]},
                    }
                ],
            }
        )
    payload = {
        "author": member["person_urn"],
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": share_content
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
