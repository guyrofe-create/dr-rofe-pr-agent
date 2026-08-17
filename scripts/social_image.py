"""Create a topic-relevant visual package from licensed real photography.

The product searches Wikimedia Commons for a verified photograph with a
compatible license, records its provenance, and fails closed when no suitable
photo is found. This module never generates images with AI.
"""

import base64
import html
import json
import os
import re
import time
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

from reputation_core.strategy import load_client_profile
from reputation_core.ai_usage import record_ai_usage

_CLIENT_FACTS = load_client_profile()["canonical_facts"]
_CLIENT_NAME = _CLIENT_FACTS["primary_name"]
_CLIENT_SITE = _CLIENT_FACTS["canonical_site"]
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"
PEXELS_API_URL = "https://api.pexels.com/v1/search"
PIXABAY_API_URL = "https://pixabay.com/api/"
DEFAULT_IMAGE_PATH = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "default-reputation-image.png"
)
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
PLANNED_SEARCH_QUERIES = 5
MAX_SEARCH_QUERIES = 8
MAX_REVIEWED_CANDIDATES = 24
MAX_REVIEWED_PER_QUERY = 3
TRANSIENT_WORDPRESS_HTTP = {408, 429, 500, 502, 503, 504}
QUERY_NOISE_WORDS = frozenset(
    {
        "and",
        "at",
        "comparing",
        "cross",
        "cross-checking",
        "evaluating",
        "for",
        "information",
        "in",
        "online",
        "on",
        "photograph",
        "public",
        "reference",
        "researching",
        "sources",
        "studying",
        "using",
        "websites",
        "with",
    }
)


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
    source_type: str = "manual"
    generation_model: str = ""
    generation_prompt: str = ""
    variants: dict[str, bytes] = field(default_factory=dict)


def visual_description(title):
    clean_title = " ".join((title or "מידע כללי").split())
    return f"איור מערכתי ללא מלל בנושא {_topic_without_client(clean_title)}"[:300]


def alt_text(title, description=None, entity_relevant=None):
    """Describe the image accurately and add the article-owner context naturally."""
    clean_title = " ".join((title or "מידע רפואי כללי").split())
    name_variants = _CLIENT_FACTS.get("name_variants", [_CLIENT_NAME])
    relevant = bool(entity_relevant) if entity_relevant is not None else (
        any(variant in clean_title for variant in name_variants)
        or bool(entity_relevant)
    )
    base = " ".join((description or visual_description(clean_title)).split())
    if relevant:
        base = f"{base.rstrip(' .')}, מלווה מאמר של {_CLIENT_NAME}"
        for variant in sorted(name_variants, key=len, reverse=True):
            if variant != _CLIENT_NAME:
                base = base.replace(variant, "")
        while base.count(_CLIENT_NAME) > 1:
            base = base.replace(_CLIENT_NAME, "", 1)
        base = " ".join(base.split())
    return base[:300]


def _plain(value):
    """Flatten Commons HTML metadata into safe plain text."""
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def _metadata_value(metadata, key):
    value = (metadata or {}).get(key, {})
    return _plain(value.get("value") if isinstance(value, dict) else value)


def _parse_review_verdict(raw):
    verdict = " ".join(str(raw or "").split()).strip()
    match = re.match(
        r"^\**\s*(ACCEPT|REJECT)\s*\**\s*[:\-–—]\s*(.+)$",
        verdict,
        flags=re.IGNORECASE,
    )
    if not match:
        raise RuntimeError(f"Image review returned invalid output: {verdict[:180]}")
    return match.group(1).upper(), match.group(2).strip()


def _search_query_prompt(title, summary):
    return (
        "Create five English Wikimedia Commons keyword queries for a real "
        "editorial photograph that directly illustrates this Hebrew medical "
        "article. Each query must contain only 2-4 concrete searchable words, "
        "not a sentence or metaphor. Name visible subjects, objects or places. "
        "Optimize only for direct topical relevance. People, clinical settings, "
        "equipment, body parts, visible text, labels and brands are all acceptable "
        "when they genuinely illustrate the article. The source and reusable "
        "license are verified separately by the product. "
        "Return JSON only in this exact form: "
        '{"queries":["query 1","query 2","query 3","query 4","query 5"]}.\n'
        f"Preferred visible subject: {_topic_visual_brief(title)}\n"
        f"Title: {' '.join((title or '').split())}\n"
        f"Context: {' '.join((summary or '').split())[:2400]}"
    )


def topic_search_queries(title):
    """Return deterministic Commons queries for recognized medical topics."""
    topic = _topic_without_client(title)
    if "כאבי מחזור" in topic or "דיסמנוריאה" in topic:
        return [
            "experiencing menstrual pain",
            "menstrual pain",
            "period pain",
            "menstrual cramps",
        ]
    if "משמרות לילה" in topic or "עבודת לילה" in topic:
        return [
            "night duty hospital",
            "hospital at night",
            "night shift work",
            "night shift worker",
        ]
    if "מיומ" in topic:
        return [
            "gynecological ultrasound equipment",
            "transvaginal ultrasound probe",
            "ultrasound examination room",
            "medical ultrasound machine",
        ]
    if "לפרוסקופ" in topic:
        return [
            "laparoscopic surgical instruments",
            "laparoscope medical equipment",
            "minimally invasive surgery tools",
            "operating room instruments",
        ]
    if "אנדומטריוז" in topic or "פוריות" in topic:
        return [
            "fertility laboratory microscope",
            "medical research laboratory",
            "laboratory microscope equipment",
            "clinical laboratory workbench",
        ]
    if "כלב" in topic and ("שבץ" in topic or "שיקום" in topic):
        return [
            "therapy dog rehabilitation",
            "therapy dog hospital",
            "stroke rehabilitation therapy",
            "physical rehabilitation dog",
            "assistance dog therapy",
        ]
    if "שבץ" in topic or "שיקום" in topic:
        return [
            "stroke rehabilitation therapy",
            "physical rehabilitation clinic",
            "rehabilitation walking exercise",
            "occupational therapy rehabilitation",
        ]
    if "סרטן" in topic and ("דם" in topic or "בדיק" in topic):
        return [
            "blood test laboratory",
            "laboratory blood sample",
            "cancer research blood test",
            "clinical laboratory technician",
        ]
    if "פוליציסט" in topic or "PCOS" in topic.upper():
        return [
            "gynecological ultrasound equipment",
            "hormone testing laboratory",
            "laboratory test tubes",
            "ultrasound transducer clinic",
        ]
    if "כאבי אגן" in topic or "אגן כרוני" in topic:
        return [
            "pelvic anatomy model",
            "medical anatomy model",
            "medical education desk",
            "clinical teaching model",
        ]
    if "מידע רפואי" in topic or "מקור אמין" in topic or "ברשת" in topic:
        return [
            "medical research books",
            "medical library desk",
            "medical reference books",
            "health research laptop",
        ]
    if "אכילה" in topic or "לאכול" in topic or "צום" in topic:
        return [
            "healthy meal table",
            "vegetables dinner table",
            "meal preparation kitchen",
            "empty dining table",
        ]
    return []


def fallback_search_queries(title):
    """Return safe Commons queries when the optional AI planner is unavailable."""
    specific = topic_search_queries(title)
    if specific:
        return specific
    return [
        "medical research equipment",
        "clinical research laboratory",
        "medical education equipment",
        "laboratory microscope",
    ]


def build_search_queries(client, title, summary):
    model = os.environ.get("OPENAI_IMAGE_QUERY_MODEL", "gpt-5.6")
    response = client.responses.create(
        model=model,
        input=_search_query_prompt(title, summary),
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=180,
        timeout=float(os.environ.get("OPENAI_TEXT_TIMEOUT_SECONDS", "45")),
    )
    record_ai_usage(
        response,
        operation="licensed_photo_query_planning",
        model=model,
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
    return cleaned[:PLANNED_SEARCH_QUERIES]


def expand_search_queries(queries):
    """Try compact Commons keywords before the planner's more specific phrases."""
    compact = []
    original = []
    for query in queries:
        normalized = " ".join(str(query).split()).strip()
        if not normalized:
            continue
        tokens = re.findall(r"[A-Za-z0-9-]+", normalized.lower())
        reduced = [token for token in tokens if token not in QUERY_NOISE_WORDS][:4]
        shortened = " ".join(reduced)
        if len(reduced) >= 2 and shortened not in compact:
            compact.append(shortened)
        if normalized not in original:
            original.append(normalized)
    ordered = compact + [query for query in original if query not in compact]
    return ordered[:MAX_SEARCH_QUERIES]


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


def search_openverse(query, *, request_get=requests.get):
    """Return commercial-use photographs with normalized provenance metadata."""
    response = request_get(
        OPENVERSE_API_URL,
        params={
            "q": query,
            "page_size": 20,
            "category": "photograph",
            "license_type": "commercial",
            "size": "large",
            "mature": "false",
        },
        headers={("User-Agent"): COMMONS_USER_AGENT, "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    candidates = []
    for item in response.json().get("results", []):
        license_code = str(item.get("license") or "").lower()
        if license_code not in {"cc0", "pdm", "by", "by-sa"}:
            continue
        extension = str(item.get("filetype") or "").lower()
        if extension == "jpeg":
            extension = "jpg"
        if extension not in {"jpg", "png"}:
            continue
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if min(width, height) < 700:
            continue
        image_url = item.get("url")
        page_url = item.get("foreign_landing_url")
        license_url = item.get("license_url")
        if not image_url or not page_url or not license_url:
            continue
        creator = " ".join(str(item.get("creator") or "").split())
        if not creator and license_code not in {"cc0", "pdm"}:
            continue
        creator = creator or "נחלת הכלל"
        version = str(item.get("license_version") or "").strip()
        license_names = {
            "cc0": f"CC0 {version}".strip(),
            "pdm": f"Public Domain Mark {version}".strip(),
            "by": f"CC BY {version}".strip(),
            "by-sa": f"CC BY-SA {version}".strip(),
        }
        license_name = license_names[license_code]
        title = _plain(item.get("title") or "Openverse photograph")
        tags = " ".join(
            str(tag.get("name") or "")
            for tag in item.get("tags", [])
            if isinstance(tag, dict)
        )
        probe = f"{title} {tags}".lower()
        if any(marker in probe for marker in SYNTHETIC_OR_NONPHOTO_MARKERS):
            continue
        attribution = _plain(item.get("attribution")) or (
            f"{title} — {creator}; {license_name}; Openverse"
        )
        candidates.append({
            "download_url": image_url,
            "source_image_url": image_url,
            "source_page_url": page_url,
            "creator": creator,
            "license_name": license_name,
            "license_url": license_url,
            "attribution": attribution,
            "media_type": f"image/{'jpeg' if extension == 'jpg' else 'png'}",
            "extension": extension,
            "description": title,
            "source_type": "openverse_licensed_photo",
        })
    return candidates


def search_pexels(query, *, request_get=requests.get):
    """Return Pexels photographs when the optional API key is configured."""
    api_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not api_key:
        return []
    response = request_get(
        PEXELS_API_URL,
        params={"query": query, "per_page": 20, "orientation": "landscape"},
        headers={"Authorization": api_key, "User-Agent": COMMONS_USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    candidates = []
    for item in response.json().get("photos", []):
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        image_url = (item.get("src") or {}).get("large2x") or (
            item.get("src") or {}
        ).get("original")
        page_url = item.get("url")
        creator = " ".join(str(item.get("photographer") or "").split())
        if min(width, height) < 700 or not image_url or not page_url or not creator:
            continue
        candidates.append({
            "download_url": image_url,
            "source_image_url": image_url,
            "source_page_url": page_url,
            "creator": creator,
            "license_name": "Pexels License",
            "license_url": "https://www.pexels.com/legal-pages/license/",
            "attribution": f"Photo by {creator} on Pexels — {page_url}",
            "media_type": "image/jpeg",
            "extension": "jpg",
            "description": str(item.get("alt") or "Pexels photograph"),
            "source_type": "pexels_free_photo",
        })
    return candidates


def search_pixabay(query, *, request_get=requests.get):
    """Return Pixabay photos and download them instead of permanent hotlinking."""
    api_key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not api_key:
        return []
    response = request_get(
        PIXABAY_API_URL,
        params={
            "key": api_key,
            "q": query,
            "image_type": "photo",
            "safesearch": "true",
            "per_page": 20,
            "min_width": 700,
            "min_height": 700,
        },
        headers={"User-Agent": COMMONS_USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    candidates = []
    for item in response.json().get("hits", []):
        width = int(item.get("imageWidth") or 0)
        height = int(item.get("imageHeight") or 0)
        image_url = item.get("largeImageURL")
        page_url = item.get("pageURL")
        creator = " ".join(str(item.get("user") or "").split())
        if min(width, height) < 700 or not image_url or not page_url or not creator:
            continue
        candidates.append({
            "download_url": image_url,
            "source_image_url": image_url,
            "source_page_url": page_url,
            "creator": creator,
            "license_name": "Pixabay Content License",
            "license_url": "https://pixabay.com/service/license-summary/",
            "attribution": f"Image by {creator} on Pixabay — {page_url}",
            "media_type": "image/jpeg",
            "extension": "jpg",
            "description": str(item.get("tags") or "Pixabay photograph"),
            "source_type": "pixabay_free_photo",
        })
    return candidates


def interleave_candidates(*groups):
    """Prevent one provider from consuming the entire review budget."""
    merged = []
    max_length = max((len(group) for group in groups), default=0)
    for index in range(max_length):
        for group in groups:
            if index < len(group):
                merged.append(group[index])
    return merged


def review_relevance(client, image_bytes, media_type, title, summary):
    """Accept a licensed photograph based only on direct topical relevance."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    model = os.environ.get("OPENAI_IMAGE_REVIEW_MODEL", "gpt-5.6")
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                        "This photograph has already passed the product's approved-source "
                        "and reusable-license checks. Judge it only by whether the visible "
                        "content directly and truthfully illustrates the exact article. "
                        "Do not reject it because it contains people, a patient, a clinician, "
                        "a body part, a clinical setting, visible text, numbers, labels, "
                        "branding or a watermark. Reject it only when it is not topically "
                        "relevant or would materially misrepresent the article's subject. "
                        "Return exactly one line. If suitable: "
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
        timeout=float(os.environ.get("OPENAI_IMAGE_REVIEW_TIMEOUT_SECONDS", "45")),
    )
    record_ai_usage(
        response,
        operation="licensed_photo_relevance_review",
        model=model,
    )
    decision, detail = _parse_review_verdict(response.output_text)
    if decision == "ACCEPT":
        description = detail
        if len(description) < 12:
            raise RuntimeError("Photo review returned an unusable description")
        return True, description
    return False, detail


def select_licensed_photo(title, summary, client=None):
    """Select and verify a real licensed photo; never generate an image."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            timeout=float(os.environ.get("OPENAI_TEXT_TIMEOUT_SECONDS", "45")),
            max_retries=0,
        )

    planned_queries = topic_search_queries(title)
    if not planned_queries:
        try:
            planned_queries = build_search_queries(client, title, summary)
        except Exception:
            planned_queries = fallback_search_queries(title)
    queries = expand_search_queries(planned_queries)
    reviewed = 0
    downloaded = 0
    undersized = 0
    seen = set()
    rejection_reasons = []
    query_results = []
    search_errors = []
    for query in queries:
        reviewed_for_query = 0
        try:
            commons = search_commons(query)
        except requests.RequestException as exc:
            commons = []
            search_errors.append(f"{query}: {type(exc).__name__}")
        try:
            openverse = search_openverse(query)
        except requests.RequestException as exc:
            openverse = []
            search_errors.append(f"{query}/openverse: {type(exc).__name__}")
        try:
            pexels = search_pexels(query)
        except requests.RequestException as exc:
            pexels = []
            search_errors.append(f"{query}/pexels: {type(exc).__name__}")
        try:
            pixabay = search_pixabay(query)
        except requests.RequestException as exc:
            pixabay = []
            search_errors.append(f"{query}/pixabay: {type(exc).__name__}")
        candidates = interleave_candidates(commons, openverse, pexels, pixabay)
        query_results.append(
            f"{query}: commons={len(commons)}, openverse={len(openverse)}, "
            f"pexels={len(pexels)}, pixabay={len(pixabay)}"
        )
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
            reviewed_for_query += 1
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
                    source_type=candidate.get(
                        "source_type",
                        "wikimedia_commons_licensed_photo",
                    ),
                )
            rejection_reasons.append(review)
            if (
                reviewed >= MAX_REVIEWED_CANDIDATES
                or reviewed_for_query >= MAX_REVIEWED_PER_QUERY
            ):
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


def _topic_visual_brief(title):
    """Choose a concrete, medically relevant, people-free subject."""
    topic = _topic_without_client(title)
    if "מיומ" in topic:
        return (
            "gynecological ultrasound equipment and a transvaginal ultrasound "
            "probe in a clean examination room, with no people. Any monitor must "
            "be dark or show only abstract non-obstetric waveforms: absolutely no "
            "fetus, pregnancy scan, labels or readable interface"
        )
    if "לפרוסקופ" in topic:
        return (
            "laparoscopic camera equipment, trocars and minimally invasive "
            "surgical instruments arranged on a sterile blue drape in an "
            "operating room, with no people and no graphic body content"
        )
    if "אנדומטריוז" in topic or "פוריות" in topic:
        return (
            "a modern fertility research laboratory workbench with microscope, "
            "closed sample dishes and precise laboratory tools, with no people, "
            "embryos, pregnancy imagery or labels"
        )
    if "כאבי אגן" in topic or "אגן כרוני" in topic:
        return (
            "a neutral pelvic anatomy teaching model beside a closed notebook and "
            "a warm compress on a calm medical-education desk, with no people and "
            "no graphic anatomy"
        )
    if "מידע רפואי" in topic or "מקור אמין" in topic or "ברשת" in topic:
        return (
            "a laptop, magnifying glass and several medical reference books on a "
            "research desk, with no people and every screen and page fully blurred "
            "and unreadable"
        )
    return (
        "topic-relevant medical education equipment and research objects, with "
        "no people, no graphic content and no implication that the article author "
        "provides medical services"
    )


def _fit_cover(image, size):
    target_width, target_height = size
    ratio = max(target_width / image.width, target_height / image.height)
    resized = image.resize(
        (round(image.width * ratio), round(image.height * ratio)),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - target_width) // 2
    top = (resized.height - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height))


def _fit_contain(image, size, background=(255, 255, 255)):
    """Fit the complete branded default inside a platform canvas without cropping."""
    target_width, target_height = size
    foreground = image.convert("RGBA")
    ratio = min(target_width / foreground.width, target_height / foreground.height)
    resized = foreground.resize(
        (round(foreground.width * ratio), round(foreground.height * ratio)),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGBA", size, (*background, 255))
    left = (target_width - resized.width) // 2
    top = (target_height - resized.height) // 2
    canvas.alpha_composite(resized, (left, top))
    return canvas.convert("RGB")


def _topic_without_client(title):
    value = " ".join((title or "מידע רפואי מבוסס מקורות").lstrip("#").split())
    for variant in sorted(_CLIENT_FACTS.get("name_variants", []), key=len, reverse=True):
        value = value.replace(variant, "")
    return value.strip(" |–—-:") or "מידע רפואי מבוסס מקורות"


def _png_bytes(image):
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _jpeg_bytes(image):
    output = BytesIO()
    image.convert("RGB").save(
        output, format="JPEG", quality=92, optimize=True, progressive=True
    )
    return output.getvalue()


def default_branded_image(path=DEFAULT_IMAGE_PATH):
    """Return the owner-provided logo package used only when no other image exists."""
    try:
        base = Image.open(path)
        base.load()
    except Exception as exc:
        raise PhotoSelectionError(
            f"The default reputation image could not be loaded: {path}"
        ) from exc
    variants = {
        "hero": _png_bytes(_fit_contain(base, (1600, 900))),
        "landscape": _png_bytes(_fit_contain(base, (1200, 630))),
        "square": _jpeg_bytes(_fit_contain(base, (1200, 1200))),
        "portrait": _png_bytes(_fit_contain(base, (1080, 1350))),
    }
    return SocialImage(
        content=variants["landscape"],
        media_type="image/png",
        extension="png",
        visual_description="הלוגו של ד״ר גיא רופא על רקע לבן",
        creator=_CLIENT_NAME,
        license_name="Owner-provided brand asset",
        attribution="",
        source_type="owner_provided_default",
        variants=variants,
    )


def generate(title, summary, client=None):
    """Return four image variants after exhaustive search, else owner logo."""
    try:
        licensed = select_licensed_photo(title, summary, client=client)
    except PhotoSelectionError:
        return default_branded_image()
    try:
        base = Image.open(BytesIO(licensed.content)).convert("RGB")
    except Exception as exc:
        raise PhotoSelectionError(
            "The selected licensed photograph could not be decoded"
        ) from exc
    if min(base.size) < 700:
        raise PhotoSelectionError("Selected licensed photograph is too small")
    variants = {
        "hero": _png_bytes(_fit_cover(base, (1600, 900))),
        "landscape": _png_bytes(_fit_cover(base, (1200, 630))),
        # Instagram image publishing accepts JPEG; keep this approved variant
        # byte-exact through hosting instead of converting it after approval.
        "square": _jpeg_bytes(_fit_cover(base, (1200, 1200))),
        "portrait": _png_bytes(_fit_cover(base, (1080, 1350))),
    }
    return SocialImage(
        content=variants["landscape"],
        media_type="image/png",
        extension="png",
        visual_description=licensed.visual_description,
        source_page_url=licensed.source_page_url,
        source_image_url=licensed.source_image_url,
        creator=licensed.creator,
        license_name=licensed.license_name,
        license_url=licensed.license_url,
        attribution=licensed.attribution,
        source_type=licensed.source_type,
        variants=variants,
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
    """Upload an approved visual once and preserve its provenance."""
    endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/media"
    auth = (username, app_password)
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": f"ReputationAgentPublisher/1.0 (+{_CLIENT_SITE})",
    }
    lookup_args = {
        "auth": auth,
        "params": {"slug": slug, "_fields": "id,source_url,slug"},
        "headers": headers,
        "timeout": 25,
    }
    lookup = None
    existing = None
    last_decode_error = None
    for attempt in range(3):
        try:
            lookup = requests.get(endpoint, **lookup_args)
            if lookup.status_code in TRANSIENT_WORDPRESS_HTTP and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            lookup.raise_for_status()
            try:
                existing = lookup.json()
                break
            except ValueError as exc:
                last_decode_error = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    if existing is None:
        content_type = ""
        if lookup is not None:
            content_type = str(lookup.headers.get("Content-Type") or "")
        detail = f" (Content-Type: {content_type})" if content_type else ""
        raise RuntimeError(
            "WordPress media lookup returned a non-JSON response" + detail
        ) from last_decode_error
    if not isinstance(existing, list):
        if isinstance(existing, dict):
            code = existing.get("code") or "unexpected_object"
            message = existing.get("message") or "no message"
            raise RuntimeError(
                "WordPress media lookup returned an object instead of a list: "
                f"{code}: {message}"
            )
        raise RuntimeError(
            "WordPress media lookup returned an unexpected JSON response"
        )
    if existing:
        source_url = existing[0].get("source_url")
        if not source_url:
            raise RuntimeError("WordPress existing media item returned no media URL")
        return source_url

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

    generated = image.source_type in {
        "openai_generated_text_free_visual",
        "deterministic_text_free_fallback",
    }
    if image.source_type == "owner_provided_default":
        caption = ""
        description = f"תמונת ברירת־מחדל ממותגת שסופקה על ידי {_CLIENT_NAME}."
    elif generated:
        caption = ""
        description = (
            f"תמונה ללא מלל שנוצרה עבור מאמר של {_CLIENT_NAME} באמצעות "
            f"{image.generation_model or 'מנוע מקומי'}."
        )
    else:
        caption = image.attribution
        description = (
            f"מקור: {image.source_page_url}\nרישיון: "
            f"{image.license_name} {image.license_url}"
        )
    metadata = requests.post(
        f"{endpoint}/{media_id}",
        auth=auth,
        json={
            "slug": slug,
            "title": title,
            "alt_text": alt_text(title, image.visual_description),
            "caption": caption,
            "description": description,
        },
        headers=headers,
        timeout=30,
    )
    metadata.raise_for_status()
    return source_url
