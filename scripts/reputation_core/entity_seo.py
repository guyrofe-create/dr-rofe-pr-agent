"""Entity SEO primitives for one configurable single-tenant installation.

The module deliberately separates *describing* an entity from *publishing*
markup.  Callers can audit and preview every payload before an approved public
write.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlparse


def _canonical_site(profile: dict) -> dict:
    return next(
        (site for site in profile.get("sites", []) if site.get("canonical")),
        profile.get("sites", [{}])[0],
    )


def canonical_url(profile: dict) -> str:
    site = _canonical_site(profile)
    return (site.get("canonical_url") or site.get("base_url") or "").rstrip("/") + "/"


def person_id(profile: dict) -> str:
    return canonical_url(profile) + "#person"


def profile_page_url(profile: dict) -> str:
    explicit = (profile.get("profilePageUrl") or "").strip()
    return explicit or canonical_url(profile) + "profile/"


def build_person_schema(profile: dict) -> dict:
    person = {
        "@type": "Person",
        "@id": person_id(profile),
        "name": profile["name"],
        "url": canonical_url(profile),
        "mainEntityOfPage": {"@id": profile_page_url(profile) + "#profilepage"},
    }
    for key in (
        "alternateName",
        "honorificPrefix",
        "image",
        "description",
        "jobTitle",
        "knowsLanguage",
        "knowsAbout",
        "sameAs",
    ):
        if profile.get(key):
            person[key] = profile[key]
    if profile.get("nationality"):
        person["nationality"] = {
            "@type": "Country",
            "name": profile["nationality"],
        }
    return person


def build_profile_page_schema(profile: dict, page_url: str | None = None) -> dict:
    page_url = (page_url or profile_page_url(profile)).rstrip("/") + "/"
    page = {
        "@type": "ProfilePage",
        "@id": page_url + "#profilepage",
        "url": page_url,
        "name": f"{profile['name']} — פרופיל רשמי",
        "mainEntity": {"@id": person_id(profile)},
        "inLanguage": profile.get("primaryLanguage", "he"),
    }
    if profile.get("dateModified"):
        page["dateModified"] = profile["dateModified"]
    return {
        "@context": "https://schema.org",
        "@graph": [page, build_person_schema(profile)],
    }


def extract_citation_urls(markdown: str) -> list[str]:
    urls = re.findall(r"https?://[^\s)<>\]]+", markdown or "")
    seen = set()
    result = []
    for url in urls:
        clean = url.rstrip(".,;:")
        if clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def build_article_schema(
    profile: dict,
    *,
    headline: str,
    article_url: str,
    description: str,
    date_published: str | None = None,
    date_modified: str | None = None,
    image_url: str | None = None,
    citations: list[str] | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "@id": article_url.rstrip("/") + "/#article",
        "headline": headline,
        "description": description,
        "url": article_url,
        "mainEntityOfPage": {"@id": article_url},
        "author": {
            "@type": "Person",
            "@id": person_id(profile),
            "name": profile["name"],
            "url": profile_page_url(profile),
        },
        "datePublished": date_published or now,
        "dateModified": date_modified or date_published or now,
        "inLanguage": profile.get("primaryLanguage", "he"),
    }
    if image_url or profile.get("image"):
        schema["image"] = [image_url or profile["image"]]
    if citations:
        schema["citation"] = list(dict.fromkeys(citations))
    return schema


def json_ld_script(schema: dict) -> str:
    payload = json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/")
    return f'<script type="application/ld+json">{payload}</script>'


def render_profile_page(profile: dict, page_url: str | None = None) -> str:
    """Visible, factual profile content plus matching JSON-LD."""
    names = " · ".join(profile.get("alternateName", []))
    links = "".join(
        f'<li><a rel="me" href="{escape(url)}">{escape(urlparse(url).netloc)}</a></li>'
        for url in profile.get("sameAs", [])
    )
    return "\n".join(
        [
            f"<h1>{escape(profile['name'])}</h1>",
            f"<p>{escape(profile.get('description', ''))}</p>",
            f"<p><strong>שמות נוספים:</strong> {escape(names)}</p>" if names else "",
            f"<ul>{links}</ul>" if links else "",
            json_ld_script(build_profile_page_schema(profile, page_url=page_url)),
        ]
    )


@dataclass(frozen=True)
class ContentQualityReport:
    passed: bool
    checks: dict[str, bool]
    warnings: tuple[str, ...]


def audit_article_markdown(markdown: str) -> ContentQualityReport:
    """Audit answer-first structure without forcing useless tables or FAQs."""
    text = markdown or ""
    body = re.sub(r"^#\s+.+$", "", text, count=1, flags=re.MULTILINE).strip()
    first_block = next(
        (block.strip() for block in re.split(r"\n\s*\n", body) if block.strip()),
        "",
    )
    sources = extract_citation_urls(text)
    has_faq_heading = bool(re.search(r"^##+\s+.*(?:שאלות|FAQ)", text, re.MULTILINE | re.I))
    faq_questions = len(re.findall(r"^###\s+.+[?？]\s*$", text, re.MULTILINE))
    checks = {
        "single_h1": len(re.findall(r"^#\s+", text, re.MULTILINE)) == 1,
        "clear_h2_structure": len(re.findall(r"^##\s+", text, re.MULTILINE)) >= 2,
        "answer_first": 20 <= len(re.sub(r"\s+", " ", first_block)) <= 900,
        "cited_sources": len(sources) >= 2,
        "faq_valid_when_present": not has_faq_heading or faq_questions >= 2,
    }
    warnings = []
    if not checks["answer_first"]:
        warnings.append("הפתיחה צריכה לתת תשובה ישירה לפני ההרחבה")
    if not checks["cited_sources"]:
        warnings.append("נדרשים לפחות שני מקורות ישירים; יש להעדיף מקורות ראשוניים")
    if not checks["faq_valid_when_present"]:
        warnings.append("FAQ מותר רק כאשר קיימות שאלות ותשובות שימושיות בפועל")
    return ContentQualityReport(
        passed=all(checks.values()),
        checks=checks,
        warnings=tuple(warnings),
    )


def validate_media_metadata(media: dict) -> list[str]:
    """Return actionable errors for images and videos."""
    errors = []
    media_type = media.get("type")
    if media_type == "image":
        if not (media.get("visual_description") or "").strip():
            errors.append("image_visual_description_required")
        if not (media.get("alt_text") or "").strip():
            errors.append("image_alt_text_required")
        if media.get("entity_named") and not media.get("entity_relevant"):
            errors.append("entity_name_in_alt_without_visual_relevance")
    elif media_type == "video":
        if not (media.get("transcript") or "").strip():
            errors.append("video_transcript_required")
        if not (media.get("captions") or "").strip():
            errors.append("video_captions_required")
    else:
        errors.append("unsupported_media_type")
    return errors
