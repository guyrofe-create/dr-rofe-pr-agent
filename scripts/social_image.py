"""Create a topic-relevant editorial visual and exact branded social variants.

GPT Image supplies the text-free editorial base when available. Exact Hebrew
copy and client identity are rendered deterministically. A local branded
fallback guarantees that a review bundle never finishes without an image.
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
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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
PLANNED_SEARCH_QUERIES = 5
MAX_SEARCH_QUERIES = 10
MAX_REVIEWED_CANDIDATES = 12
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
    source_type: str = "openai_generated_branded_visual"
    generation_model: str = ""
    generation_prompt: str = ""
    variants: dict[str, bytes] = field(default_factory=dict)


def visual_description(title):
    clean_title = " ".join((title or "מידע כללי").split())
    return (
        f"כרטיס מידע ממותג של {_CLIENT_NAME} עם רקע מערכתי "
        f"הקשור לנושא: {clean_title}"
    )[:300]


def alt_text(title, description=None, entity_relevant=None):
    """Describe only what is visible; add the entity name only when relevant."""
    clean_title = " ".join((title or "מידע רפואי כללי").split())
    name_variants = _CLIENT_FACTS.get("name_variants", [_CLIENT_NAME])
    relevant = bool(entity_relevant) if entity_relevant is not None else (
        any(variant in clean_title for variant in name_variants)
        or "כרטיס מידע ממותג" in str(description or "")
    )
    base = " ".join((description or visual_description(clean_title)).split())
    if relevant:
        base = f"כרטיס מידע של {_CLIENT_NAME} בנושא {_topic_without_client(clean_title)}"
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
        "Create five English Wikimedia Commons keyword queries for a real "
        "editorial photograph that directly illustrates this Hebrew medical "
        "article. Each query must contain only 2-4 concrete searchable words, "
        "not a sentence or metaphor. Name visible subjects, objects or places. "
        "Do not request a doctor, clinic, surgery, text, "
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


def select_licensed_photo(title, summary, client=None):
    """Select and verify a real licensed photo; never generate an image."""
    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        planned_queries = build_search_queries(client, title, summary)
    except Exception as exc:
        raise PhotoSelectionError(
            "Licensed photo search planning failed. The draft was preserved and "
            f"queued for a replacement image. Diagnostics: planner={type(exc).__name__}"
        ) from exc
    queries = expand_search_queries(planned_queries)
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


def _image_prompt(title, summary):
    exclusions = ", ".join(str(item) for item in _VISUAL_EXCLUSIONS)
    return (
        "Create a premium editorial hero image for a Hebrew evidence-based "
        "medical information article. Use a calm, sophisticated teal, navy and "
        "warm neutral palette, photographic or high-end editorial collage style, "
        "with generous negative space. The visual must illustrate the topic "
        "without making a diagnostic or treatment claim. Do not depict a doctor, "
        "patient consultation, clinic, surgery, procedure, anatomy, medication, "
        "logos, faces presented as the author, or readable text. Do not add any "
        "letters, words, labels, captions, watermarks or typography; exact Hebrew "
        "branding will be added later by software. Avoid: "
        f"{exclusions or 'none'}.\n"
        f"Article title: {' '.join((title or '').split())}\n"
        f"Article context: {' '.join((summary or '').split())[:1800]}"
    )


def _response_image_bytes(response):
    item = response.data[0]
    encoded = getattr(item, "b64_json", None)
    if encoded:
        return base64.b64decode(encoded)
    url = getattr(item, "url", None)
    if url:
        download = requests.get(url, timeout=60)
        download.raise_for_status()
        return download.content
    raise RuntimeError("Image API returned neither b64_json nor URL")


def _generate_editorial_base(client, title, summary):
    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
    prompt = _image_prompt(title, summary)
    response = client.images.generate(
        model=model,
        prompt=prompt,
        size="1536x1024",
        quality=os.environ.get("OPENAI_IMAGE_QUALITY", "high"),
        output_format="png",
    )
    content = _response_image_bytes(response)
    image = Image.open(BytesIO(content)).convert("RGB")
    if min(image.size) < 700:
        raise RuntimeError("Generated editorial visual is too small")
    return image, model, prompt


def _fallback_editorial_base():
    width, height = 1600, 1067
    image = Image.new("RGB", (width, height), "#123b57")
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(height):
        ratio = y / max(height - 1, 1)
        color = (
            int(18 + 28 * ratio),
            int(59 + 62 * ratio),
            int(87 + 55 * ratio),
        )
        draw.line((0, y, width, y), fill=color)
    draw.ellipse((-180, 420, 740, 1340), fill=(42, 157, 143, 115))
    draw.ellipse((980, -280, 1820, 560), fill=(238, 181, 98, 80))
    draw.rounded_rectangle(
        (900, 380, 1480, 820),
        radius=70,
        fill=(255, 255, 255, 28),
        outline=(255, 255, 255, 48),
        width=3,
    )
    return image.filter(ImageFilter.GaussianBlur(radius=0.6))


def _font(size, bold=False):
    candidates = [
        (
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
            if bold
            else "/System/Library/Fonts/Supplemental/Arial.ttf"
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _display_rtl(value):
    try:
        from bidi.algorithm import get_display

        return get_display(value)
    except ImportError:
        return value[::-1]


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


def _wrap_rtl(draw, text, font, max_width, max_lines=3):
    words = text.split()
    lines = []
    current = []
    for word in words:
        proposal = " ".join([*current, word])
        width = draw.textbbox((0, 0), _display_rtl(proposal), font=font)[2]
        if current and width > max_width:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" .") + "…"
    return lines


def _render_branded_variant(base, size, title):
    image = _fit_cover(base, size)
    image = ImageEnhance.Contrast(image).enhance(0.92)
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    width, height = size
    draw.rectangle((0, 0, width, height), fill=(7, 28, 43, 80))
    draw.rounded_rectangle(
        (
            round(width * 0.07),
            round(height * 0.10),
            round(width * 0.93),
            round(height * 0.90),
        ),
        radius=max(24, round(min(size) * 0.035)),
        fill=(9, 34, 50, 198),
        outline=(255, 255, 255, 55),
        width=2,
    )
    name_font = _font(max(28, round(width * 0.034)), bold=True)
    title_font = _font(max(38, round(width * 0.056)), bold=True)
    small_font = _font(max(21, round(width * 0.021)))
    right = round(width * 0.86)
    top = round(height * 0.18)
    draw.text(
        (right, top),
        _display_rtl(_CLIENT_NAME),
        font=name_font,
        fill=(122, 225, 211, 255),
        anchor="ra",
    )
    draw.line(
        (round(width * 0.14), top + round(height * 0.09), right, top + round(height * 0.09)),
        fill=(122, 225, 211, 180),
        width=max(2, round(width * 0.003)),
    )
    subject = _topic_without_client(title)
    lines = _wrap_rtl(draw, subject, title_font, round(width * 0.70), max_lines=3)
    y = top + round(height * 0.17)
    line_height = round(title_font.size * 1.22)
    for line in lines:
        draw.text(
            (right, y),
            _display_rtl(line),
            font=title_font,
            fill="white",
            anchor="ra",
        )
        y += line_height
    draw.text(
        (right, round(height * 0.83)),
        _display_rtl("מידע רפואי מבוסס מקורות"),
        font=small_font,
        fill=(230, 238, 241, 235),
        anchor="ra",
    )
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _png_bytes(image):
    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate(title, summary, client=None):
    """Generate branded visuals and always return an approval-ready image."""
    source_type = "openai_generated_branded_visual"
    model = ""
    prompt = _image_prompt(title, summary)
    try:
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        base, model, prompt = _generate_editorial_base(client, title, summary)
    except Exception:
        base = _fallback_editorial_base()
        source_type = "deterministic_branded_fallback"
        model = "local-template-v1"
    variants = {
        "hero": _png_bytes(_fit_cover(base, (1600, 900))),
        "landscape": _png_bytes(_render_branded_variant(base, (1200, 630), title)),
        "square": _png_bytes(_render_branded_variant(base, (1200, 1200), title)),
        "portrait": _png_bytes(_render_branded_variant(base, (1080, 1350), title)),
    }
    description = visual_description(title)
    return SocialImage(
        content=variants["landscape"],
        media_type="image/png",
        extension="png",
        visual_description=description,
        creator="OpenAI and Dr. Rofe Reputation Agent",
        attribution=(
            "Visual created with OpenAI and deterministically branded for "
            f"{_CLIENT_NAME}"
            if source_type == "openai_generated_branded_visual"
            else f"Deterministic branded visual for {_CLIENT_NAME}"
        ),
        source_type=source_type,
        generation_model=model,
        generation_prompt=prompt,
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
        "openai_generated_branded_visual",
        "deterministic_branded_fallback",
    }
    if generated:
        caption = ""
        description = (
            f"נוצר עבור {_CLIENT_NAME} באמצעות "
            f"{image.generation_model or 'מנוע המיתוג המקומי'}; "
            "הטקסט והמיתוג נוספו באופן דטרמיניסטי במוצר."
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
