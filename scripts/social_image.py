"""Select a real, licensed, topic-relevant editorial photograph.

This module deliberately has no image-generation path. Review images are
downloaded from Wikimedia Commons only after their licence and provenance have
been captured, then visually checked against the exact article.
"""

import base64
import html
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import quote

import requests

from reputation_core.strategy import load_client_profile

_CLIENT_FACTS = load_client_profile()["canonical_facts"]
_CLIENT_NAME = _CLIENT_FACTS["primary_name"]
_CLIENT_SITE = _CLIENT_FACTS["canonical_site"]
_VISUAL_EXCLUSIONS = load_client_profile().get(
    "publication_guardrails", {}
).get("visual_exclusions", [])

COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
COMMONS_USER_AGENT = (
    f"ReputationAgentPublisher/1.0 ({_CLIENT_SITE}; licensed-photo-selector)"
)
ALLOWED_LICENSE_MARKERS = (
    "cc0",
    "public domain",
    "cc by ",
    "cc-by-",
    "cc by-sa",
    "cc-by-sa",
)
SYNTHETIC_OR_NONPHOTO_MARKERS = (
    "ai-generated",
    "ai generated",
    "artificial intelligence",
    "midjourney",
    "stable diffusion",
    "dall-e",
    "illustration",
    "watercolor",
    "painting",
    "drawing",
    "diagram",
    "render",
    "vector",
    "cgi",
    "computer-generated",
)
MAX_SEARCH_QUERIES = 5
MAX_REVIEWED_CANDIDATES = 12


class PhotoSelectionError(RuntimeError):
    """No safe licensed photo was selected; callers may queue manual recovery."""


@dataclass(frozen=True)
class SocialImage:
    content: bytes
    media_type: str = "image/jpeg"
    extension: str = "jpg"
    visual_description: str = ""
    source_page_url: str = ""
    source_image_url: str = ""
    creator: str = ""
    license_name: str = ""
    license_url: str = ""
    attribution: str = ""
    source_type: str = "wikimedia_commons_licensed_photo"


def visual_description(title):
    clean_title = " ".join((title or "מידע כללי").split())
    return f"צילום אמיתי הקשור ישירות לנושא הפוסט: {clean_title}"[:300]


def alt_text(title, description=None, entity_relevant=None):
    """Describe only what is visible; add the entity name only when relevant."""
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


def _plain(value):
    """Flatten Commons HTML metadata into safe plain text."""
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def _metadata_value(metadata, key):
    value = (metadata or {}).get(key, {})
    return _plain(value.get("value") if isinstance(value, dict) else value)


def _search_query_prompt(title, summary):
    exclusions = ", ".join(str(item) for item in _VISUAL_EXCLUSIONS)
    return (
        "Create five short English Wikimedia Commons search queries for a real "
        "editorial photograph that directly illustrates this Hebrew medical "
        "article. Each query must name a concrete, photographable subject or "
        "scene, not a metaphor. Do not request a doctor, clinic, surgery, text, "
        "diagram, illustration, infographic, icon, or AI image. Avoid these "
        f"client exclusions: {exclusions or 'none'}. For articles about evaluating "
        "online information, prefer an adult comparing information on a laptop or "
        "tablet, consulting reference books, or studying in a library; do not "
        "request screenshots or readable on-screen text. "
        "Return JSON only in this exact form: "
        '{"queries":["query 1","query 2","query 3","query 4","query 5"]}.\n'
        f"Title: {' '.join((title or '').split())}\n"
        f"Context: {' '.join((summary or '').split())[:2400]}"
    )


def build_search_queries(client, title, summary):
    response = client.responses.create(
        model=os.environ.get("OPENAI_IMAGE_QUERY_MODEL", "gpt-5.6"),
        input=_search_query_prompt(title, summary),
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=180,
    )
    raw = (response.output_text or "").strip()
    raw = re.sub(r"\A```(?:json)?\s*|\s*```\Z", "", raw, flags=re.IGNORECASE)
    try:
        queries = json.loads(raw)["queries"]
    except (ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Photo search planner returned invalid JSON") from exc
    cleaned = []
    for query in queries:
        item = " ".join(str(query).split()).strip()
        if item and item not in cleaned:
            cleaned.append(item)
    if len(cleaned) < 3:
        raise RuntimeError("Photo search planner returned too few usable queries")
    return cleaned[:MAX_SEARCH_QUERIES]


def _candidate_from_page(page):
    imageinfo = (page.get("imageinfo") or [{}])[0]
    metadata = imageinfo.get("extmetadata") or {}
    mime = str(imageinfo.get("mime") or "").lower()
    width = int(imageinfo.get("width") or 0)
    height = int(imageinfo.get("height") or 0)
    if mime not in {"image/jpeg", "image/png"} or min(width, height) < 700:
        return None

    license_name = _metadata_value(metadata, "LicenseShortName")
    license_url = _metadata_value(metadata, "LicenseUrl")
    license_probe = f"{license_name} {license_url}".lower()
    if not any(marker in license_probe for marker in ALLOWED_LICENSE_MARKERS):
        return None

    title = _plain(page.get("title", "")).removeprefix("File:")
    description = _metadata_value(metadata, "ImageDescription")
    categories = _metadata_value(metadata, "Categories")
    probe = f"{title} {description} {categories}".lower()
    if any(marker in probe for marker in SYNTHETIC_OR_NONPHOTO_MARKERS):
        return None

    creator = (
        _metadata_value(metadata, "Artist")
        or _metadata_value(metadata, "Credit")
        or _metadata_value(metadata, "Attribution")
    )
    if not creator and "public domain" not in license_probe and "cc0" not in license_probe:
        return None
    page_url = (
        page.get("canonicalurl")
        or page.get("fullurl")
        or f"https://commons.wikimedia.org/wiki/File:{quote(title)}"
    )
    image_url = imageinfo.get("thumburl") or imageinfo.get("url")
    original_url = imageinfo.get("url") or image_url
    if not image_url:
        return None
    extension = "png" if mime == "image/png" else "jpg"
    credit_name = creator or "נחלת הכלל"
    attribution = (
        f"{title} — {credit_name}; {license_name}; Wikimedia Commons"
    )
    return {
        "download_url": image_url,
        "source_image_url": original_url,
        "source_page_url": page_url,
        "creator": credit_name,
        "license_name": license_name,
        "license_url": license_url,
        "attribution": attribution,
        "media_type": mime,
        "extension": extension,
        "description": description,
    }


def search_commons(query, *, request_get=requests.get):
    """Return reusable bitmap-photo candidates with full licence metadata."""
    response = request_get(
        COMMONS_API_URL,
        params={
            "action": "query",
            "format": "json",
            "formatversion": "2",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": "30",
            "prop": "info|imageinfo",
            "inprop": "url",
            "iiprop": "url|mime|size|extmetadata",
            "iiurlwidth": "1600",
        },
        headers={"User-Agent": COMMONS_USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", [])
    return [
        candidate
        for page in pages
        if (candidate := _candidate_from_page(page)) is not None
    ]


def review_relevance(client, image_bytes, media_type, title, summary):
    """Accept only a real-looking photo that directly supports the article."""
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
                            "Act as a strict senior medical photo editor. This is "
                            "an existing licensed photograph, not a generation "
                            "request. Accept it only if it is clearly relevant to "
                            "the exact article and is a normal believable photo. "
                            "Reject generic wellness imagery, doctors or clinics "
                            "not required by the article, illustrations, diagrams, "
                            "screenshots, text-heavy images, or content that could "
                            "mislead readers. Return exactly one line. If suitable: "
                            "ACCEPT: followed by a concrete truthful Hebrew alt-text "
                            "description of only what is visibly present. Otherwise: "
                            "REJECT: followed by a short reason.\n\n"
                            f"Title: {title}\n"
                            f"Context: {' '.join((summary or '').split())[:2400]}"
                        ),
                    },
                    {
                        "type": "input_image",
                        "image_url": f"data:{media_type};base64,{encoded}",
                    },
                ],
            }
        ],
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=180,
    )
    verdict = " ".join((response.output_text or "").split())
    if verdict.upper().startswith("ACCEPT:"):
        description = verdict.split(":", 1)[1].strip()
        if len(description) < 12:
            raise RuntimeError("Photo review returned an unusable description")
        return True, description
    if verdict.upper().startswith("REJECT:"):
        return False, verdict.split(":", 1)[1].strip()
    raise RuntimeError(f"Photo review returned an invalid verdict: {verdict[:120]}")


def generate(title, summary, client=None):
    """Select and verify a real licensed photo; never generate an image."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        queries = build_search_queries(client, title, summary)
    except Exception as exc:
        raise PhotoSelectionError(
            "Licensed photo search planning failed. The draft was preserved and "
            f"queued for a replacement image. Diagnostics: planner={type(exc).__name__}"
        ) from exc
    reviewed = 0
    downloaded = 0
    undersized = 0
    seen = set()
    rejection_reasons = []
    query_results = []
    search_errors = []
    for query in queries:
        try:
            candidates = search_commons(query)
        except requests.RequestException as exc:
            search_errors.append(f"{query}: {type(exc).__name__}")
            continue
        query_results.append(f"{query}: {len(candidates)} licensed candidates")
        for candidate in candidates:
            source = candidate["source_image_url"]
            if source in seen:
                continue
            seen.add(source)
            try:
                download = requests.get(
                    candidate["download_url"],
                    headers={"User-Agent": COMMONS_USER_AGENT},
                    timeout=45,
                )
                download.raise_for_status()
            except requests.RequestException as exc:
                search_errors.append(
                    f"{candidate['source_page_url']}: {type(exc).__name__}"
                )
                continue
            content = download.content
            downloaded += 1
            if len(content) < 20_000:
                undersized += 1
                continue
            try:
                accepted, review = review_relevance(
                    client,
                    content,
                    candidate["media_type"],
                    title,
                    summary,
                )
            except Exception as exc:
                search_errors.append(
                    f"{candidate['source_page_url']}: review={type(exc).__name__}"
                )
                continue
            reviewed += 1
            if accepted:
                return SocialImage(
                    content=content,
                    media_type=candidate["media_type"],
                    extension=candidate["extension"],
                    visual_description=review,
                    source_page_url=candidate["source_page_url"],
                    source_image_url=candidate["source_image_url"],
                    creator=candidate["creator"],
                    license_name=candidate["license_name"],
                    license_url=candidate["license_url"],
                    attribution=candidate["attribution"],
                )
            rejection_reasons.append(review)
            if reviewed >= MAX_REVIEWED_CANDIDATES:
                break
        if reviewed >= MAX_REVIEWED_CANDIDATES:
            break
    diagnostics = [
        f"queries={len(queries)}",
        f"unique_candidates={len(seen)}",
        f"downloaded={downloaded}",
        f"undersized={undersized}",
        f"reviewed={reviewed}",
        f"rejected={len(rejection_reasons)}",
    ]
    if query_results:
        diagnostics.append("search=[" + " | ".join(query_results) + "]")
    if rejection_reasons:
        diagnostics.append(
            "review_notes=[" + " | ".join(rejection_reasons[-5:]) + "]"
        )
    if search_errors:
        diagnostics.append("errors=[" + " | ".join(search_errors[-5:]) + "]")
    raise PhotoSelectionError(
        "No suitably licensed, topic-relevant real photograph was found. "
        "The draft was preserved and queued for a replacement image instead of "
        "using a generic or AI image. Diagnostics: "
        + "; ".join(diagnostics)
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
    """Upload an approved licensed photo once and preserve its attribution."""
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
            "caption": image.attribution,
            "description": (
                f"מקור: {image.source_page_url}\nרישיון: "
                f"{image.license_name} {image.license_url}"
            ),
        },
        headers=headers,
        timeout=30,
    )
    metadata.raise_for_status()
    return source_url
