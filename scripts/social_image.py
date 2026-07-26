"""Generate a conservative social visual with OpenAI and host it on WordPress."""

import base64
import os
from dataclasses import dataclass

import requests

from reputation_core.strategy import load_client_profile

_CLIENT_FACTS = load_client_profile()["canonical_facts"]
_CLIENT_NAME = _CLIENT_FACTS["primary_name"]
_CLIENT_SITE = _CLIENT_FACTS["canonical_site"]
_VISUAL_EXCLUSIONS = load_client_profile().get(
    "publication_guardrails", {}
).get("visual_exclusions", [])


@dataclass(frozen=True)
class SocialImage:
    content: bytes
    media_type: str = "image/png"
    extension: str = "png"


def alt_text(title):
    """Natural, accessible attribution without keyword stuffing."""
    clean_title = " ".join((title or "מידע רפואי כללי").split())
    name_variants = _CLIENT_FACTS.get("name_variants", [_CLIENT_NAME])
    if any(variant in clean_title for variant in name_variants):
        return f"{clean_title} — איור מידע כללי"[:300]
    return f"{_CLIENT_NAME} — איור מידע כללי בנושא {clean_title}"[:300]


def build_prompt(title, summary):
    """Return a brand-safe prompt that avoids medical or availability claims."""
    context = " ".join((summary or "").split())[:600]
    exclusions = "\n".join(f"- no {item}" for item in _VISUAL_EXCLUSIONS)
    return f"""
Create a polished square editorial illustration for an educational Hebrew
information post published by {_CLIENT_NAME}.

Post title: {title}
Post context: {context}

Visual direction:
- sophisticated abstract editorial composition
- calm navy, turquoise, white and soft neutral palette
- trustworthy, modern, restrained and suitable for a professional information brand
- clear central visual idea with generous negative space
- optimized for Facebook and Pinterest at small display sizes

Strict exclusions:
- no text, letters, numbers, typography, logo or watermark
{exclusions}
""".strip()


def generate(title, summary, client=None):
    """Generate one PNG using the configured OpenAI image model."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    response = client.images.generate(
        model=os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2"),
        prompt=build_prompt(title, summary),
        size=os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024"),
        quality=os.environ.get("OPENAI_IMAGE_QUALITY", "medium"),
        output_format="png",
    )
    encoded = response.data[0].b64_json
    if not encoded:
        raise RuntimeError("OpenAI image generation returned no image data")
    return SocialImage(content=base64.b64decode(encoded, validate=True))


def upload_to_wordpress(
    image,
    *,
    base_url,
    username,
    app_password,
    slug,
    title,
):
    """Upload an image once and return its public WordPress media URL."""
    endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/media"
    auth = (username, app_password)
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": f"ReputationAgentPublisher/1.0 (+{_CLIENT_SITE})",
    }
    lookup = requests.get(
        endpoint,
        params={"slug": slug, "_fields": "id,source_url,slug"},
        headers=headers,
        timeout=25,
    )
    lookup.raise_for_status()
    existing = lookup.json()
    if existing:
        return existing[0]["source_url"]

    response = requests.post(
        endpoint,
        auth=auth,
        data=image.content,
        headers={
            **headers,
            "Content-Type": image.media_type,
            "Content-Disposition": (
                f'attachment; filename="{slug}.{image.extension}"'
            ),
        },
        timeout=60,
    )
    response.raise_for_status()
    media = response.json()
    media_id = media.get("id")
    source_url = media.get("source_url")
    if not media_id or not source_url:
        raise RuntimeError("WordPress media upload returned no media URL")

    metadata = requests.post(
        f"{endpoint}/{media_id}",
        auth=auth,
        json={
            "slug": slug,
            "title": title,
            "alt_text": alt_text(title),
            "caption": "איור מידע כללי שנוצר באמצעות OpenAI",
        },
        headers=headers,
        timeout=30,
    )
    metadata.raise_for_status()
    return source_url
