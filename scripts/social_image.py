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
from dataclasses import dataclass, field
from io import BytesIO
from urllib.parse import quote

import requests
from PIL import Image

from reputation_core.strategy import load_client_profile

_CLIENT_FACTS = load_client_profile()["canonical_facts"]
_CLIENT_NAME = _CLIENT_FACTS["primary_name"]
_CLIENT_SITE = _CLIENT_FACTS["canonical_site"]
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
PLANNED_SEARCH_QUERIES = 5
MAX_SEARCH_QUERIES = 4
MAX_REVIEWED_CANDIDATES = 8
MAX_REVIEWED_PER_QUERY = 2
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
        "Prefer relevant medical equipment, instruments, research objects or an "
        "empty clinical environment. Do not request any person, exposed body, "
        "body-part close-up, patient, doctor treating a patient, readable text, "
        "brand, logo, a diagram, illustration, infographic, icon, or AI image. "
        "Do not request pregnancy, fetal or newborn "
        "imagery unless the exact article requires it. For articles about evaluating "
        "online information, prefer a people-free research desk with a laptop, "
        "reference books and magnifying glass; do not request screenshots or "
        "readable on-screen text. "
        "Return JSON only in this exact form: "
        '{"queries":["query 1","query 2","query 3","query 4","query 5"]}.\n'
        f"Preferred visible subject: {_topic_visual_brief(title)}\n"
        f"Title: {' '.join((title or '').split())}\n"
        f"Context: {' '.join((summary or '').split())[:2400]}"
    )


def fallback_search_queries(title):
    """Return safe Commons queries when the optional AI planner is unavailable."""
    topic = _topic_without_client(title)
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
    if "שחלות פוליציסטיות" in topic or "PCOS" in topic.upper():
        return [
            "gynecological ultrasound equipment",
            "hormone testing laboratory",
            "medical laboratory test tubes",
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
    return [
        "medical research equipment",
        "clinical research laboratory",
        "medical education equipment",
        "laboratory microscope",
    ]


def build_search_queries(client, title, summary):
    response = client.responses.create(
        model=os.environ.get("OPENAI_IMAGE_QUERY_MODEL", "gpt-5.6"),
        input=_search_query_prompt(title, summary),
        reasoning={"effort": "low"},
        text={"verbosity": "low"},
        max_output_tokens=180,
        timeout=float(os.environ.get("OPENAI_TEXT_TIMEOUT_SECONDS", "45")),
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
                            "Reject generic wellness imagery, any person, exposed "
                            "body or body-part close-up, doctors or clinics not "
                            "required by the article, illustrations, diagrams, "
                            "screenshots, and ANY visible letter, word, number, "
                            "brand name, logo, label, watermark or readable interface "
                            "text anywhere in the image. Also reject pregnancy or fetal "
                            "imagery unless the exact article requires it, or content "
                            "that could mislead readers. Return exactly one line. If suitable: "
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
                    source_type="wikimedia_commons_licensed_photo",
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


def _topic_without_client(title):
    value = " ".join((title or "מידע רפואי מבוסס מקורות").lstrip("#").split())
    for variant in sorted(_CLIENT_FACTS.get("name_variants", []), key=len, reverse=True):
        value = value.replace(variant, "")
    return value.strip(" |–—-:") or "מידע רפואי מבוסס מקורות"


def _png_bytes(image):
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate(title, summary, client=None):
    """Return four crops of one reviewed, licensed real photograph."""
    licensed = select_licensed_photo(title, summary, client=client)
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
        "square": _png_bytes(_fit_cover(base, (1200, 1200))),
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

    generated = image.source_type in {
        "openai_generated_text_free_visual",
        "deterministic_text_free_fallback",
    }
    if generated:
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
