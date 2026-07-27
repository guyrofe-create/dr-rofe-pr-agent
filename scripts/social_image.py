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
    visual_description: str = ""


def visual_description(title):
    clean_title = " ".join((title or "מידע כללי").split())
    return (
        "איור עריכתי בגווני כחול וטורקיז, עם אלמנטים חזותיים הקשורים "
        f"ישירות ובאופן ברור לנושא הפוסט: {clean_title}"
    )[:300]


def alt_text(title, description=None, entity_relevant=None):
    """Describe the known visual; name the entity only when visually relevant."""
    clean_title = " ".join((title or "מידע רפואי כללי").split())
    name_variants = _CLIENT_FACTS.get("name_variants", [_CLIENT_NAME])
    relevant = (
        any(variant in clean_title for variant in name_variants)
        if entity_relevant is None
        else bool(entity_relevant)
    )
    base = " ".join((description or visual_description(clean_title)).split())
    if relevant and not any(variant in base for variant in name_variants):
        base = f"{base}; נושא הפרסום: {_CLIENT_NAME}"
    return base[:300]


def build_prompt(title, summary):
    """Return a topic-anchored prompt that avoids unsupported claims."""
    clean_title = " ".join((title or "מידע כללי").split())
    context = " ".join((summary or "").split())[:2400]
    exclusions = "\n".join(f"- no {item}" for item in _VISUAL_EXCLUSIONS)
    return f"""
Create a polished square editorial illustration for an educational Hebrew
information post published by {_CLIENT_NAME}.

Exact post title: {clean_title}
Article context (use this to understand the exact subject): {context}

Visual direction:
- the central visual concept MUST be unmistakably and specifically related to
  the exact post title and article context; do not create a generic health,
  wellness, technology or corporate illustration
- select two or three concrete, non-clinical visual symbols that a viewer would
  naturally associate with this exact subject, and make them the focal point
- sophisticated topic-specific editorial composition
- calm navy, turquoise, white and soft neutral palette
- trustworthy, modern, restrained and suitable for a professional information brand
- clear central visual idea with generous negative space
- optimized for reuse on WordPress, Facebook, LinkedIn, Blogger and Pinterest
  at small display sizes

Strict exclusions:
- no text, letters, numbers, typography, logo or watermark
- no unrelated generic medical icons, random people, decorative charts or
  visual concepts that could fit a different article
{exclusions}
""".strip()


def review_relevance(client, image_bytes, title, summary):
    """Return a truthful visual description or feedback for a retry."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = client.responses.create(
        model=os.environ.get("OPENAI_IMAGE_REVIEW_MODEL", "gpt-5.6"),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Review whether this image clearly and specifically "
                            "represents the post below. A generic health, wellness, "
                            "technology or corporate visual is UNRELATED even if it "
                            "looks professional.\n\n"
                            f"Title: {title}\n"
                            f"Context: {' '.join((summary or '').split())[:2400]}\n\n"
                            "Return exactly one line. If suitable: "
                            "RELATED: followed by a concrete, truthful Hebrew "
                            "description of what is visibly present, suitable as alt "
                            "text. If unsuitable: UNRELATED: followed by a short "
                            "English correction for the next image attempt."
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{encoded}",
                    },
                ],
            }
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=220,
    )
    verdict = " ".join((response.output_text or "").split())
    if verdict.upper().startswith("RELATED:"):
        description = verdict.split(":", 1)[1].strip()
        if len(description) < 12:
            raise RuntimeError("Image review returned an unusable visual description")
        return True, description
    if verdict.upper().startswith("UNRELATED:"):
        return False, verdict.split(":", 1)[1].strip()
    raise RuntimeError(f"Image review returned an invalid verdict: {verdict[:120]}")


def generate(title, summary, client=None):
    """Generate and visually verify a topic-specific PNG."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    prompt = build_prompt(title, summary)
    last_feedback = ""
    for attempt in range(1, 4):
        attempt_prompt = prompt
        if last_feedback:
            attempt_prompt += (
                "\n\nThe previous image was rejected as insufficiently related. "
                f"Correct it in this attempt: {last_feedback}"
            )
        response = client.images.generate(
            model=os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2"),
            prompt=attempt_prompt,
            size=os.environ.get("OPENAI_IMAGE_SIZE", "1024x1024"),
            quality=os.environ.get("OPENAI_IMAGE_QUALITY", "medium"),
            output_format="png",
        )
        encoded = response.data[0].b64_json
        if not encoded:
            raise RuntimeError("OpenAI image generation returned no image data")
        content = base64.b64decode(encoded, validate=True)
        related, review = review_relevance(client, content, title, summary)
        if related:
            return SocialImage(content=content, visual_description=review)
        last_feedback = review or f"attempt {attempt} was too generic"
    raise RuntimeError(
        "OpenAI could not generate a topic-relevant image after 3 reviewed attempts"
    )


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
            "alt_text": alt_text(title, image.visual_description),
            "caption": "איור מידע כללי שנוצר באמצעות OpenAI",
        },
        headers=headers,
        timeout=30,
    )
    metadata.raise_for_status()
    return source_url
