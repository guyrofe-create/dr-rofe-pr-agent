"""Deterministic SEO metadata and related-link helpers for approved articles."""
from __future__ import annotations

import html
import re
from urllib.parse import quote, unquote, urlparse


_BRAND_SUFFIX = re.compile(
    r"\s*[|｜–—-]\s*(?:ד[\"״]ר\s+גיא\s+רופא|dr\.?\s+guy\s+rofe)\s*$",
    flags=re.IGNORECASE,
)
_WORDS = re.compile(r"[\w\u0590-\u05FF]+", flags=re.UNICODE)
_STOP_WORDS = {
    "אבחון", "אפשרויות", "באמת", "בדיקה", "גורמים", "גיא", "דוקטור",
    "האם", "הכותרת", "ומה", "טיפול", "מידע", "מאחורי", "מבוססות",
    "מקורות", "מה", "מתי", "סיבות", "עומד", "רופא", "תסמינים",
}


def unbranded_title(title: str) -> str:
    """Return a concise CMS title; the SEO plugin adds the site brand once."""
    clean = " ".join((title or "").lstrip("#").split()).strip()
    while _BRAND_SUFFIX.search(clean):
        clean = _BRAND_SUFFIX.sub("", clean).strip(" |｜–—-")
    return clean


def wordpress_public_slug(title: str, *, encoded_limit: int = 180) -> str:
    """Build a readable slug that WordPress will not truncate at 200 bytes."""
    normalized_title = unbranded_title(title)
    for apostrophe in ("'", "’", "׳"):
        normalized_title = normalized_title.replace(apostrophe, "")
    base = re.sub(
        r"[^\w\u0590-\u05FF-]+", "-", normalized_title, flags=re.UNICODE
    )
    base = re.sub(r"-+", "-", base).strip("-").lower()
    selected = []
    for word in base.split("-"):
        candidate = "-".join([*selected, word])
        if len(quote(candidate, safe="-")) > encoded_limit:
            break
        selected.append(word)
    if selected:
        return "-".join(selected)
    result = ""
    for character in base:
        candidate = result + character
        if len(quote(candidate, safe="-")) > encoded_limit:
            break
        result = candidate
    return result.strip("-")


def urls_equivalent(first: str, second: str) -> bool:
    def normalized(value: str) -> str:
        parsed = urlparse(unquote(value or ""))
        host = parsed.netloc.lower().removeprefix("www.")
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        return f"{parsed.scheme.lower()}://{host}{path}"
    return normalized(first) == normalized(second)


def _trim_words(value: str, limit: int) -> str:
    value = " ".join((value or "").split()).strip(" |｜–—-")
    if len(value) <= limit:
        return value
    shortened = value[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,:;–—-")
    return shortened or value[:limit].rstrip()


def build_search_target(
    title: str,
    *,
    metadata: dict | None = None,
    canonical_name: str = "ד״ר גיא רופא",
) -> dict:
    """Describe the query intent approved for this page without keyword stuffing."""
    metadata = metadata or {}
    topic = str(metadata.get("topic") or "").strip()
    clean_title = unbranded_title(title)
    candidate = topic if topic and len(topic) <= 100 else clean_title
    primary = _trim_words(candidate, 90)
    stream = metadata.get("content_stream")
    if stream == "health_news":
        intent = "news_analysis"
    elif re.search(r"(?:איך|האם|כמה|למה|מה|מתי|\?)", primary):
        intent = "informational_question"
    else:
        intent = "informational"
    secondary = list(dict.fromkeys([
        _trim_words(clean_title, 100),
        _trim_words(f"{primary} {canonical_name}", 120),
        _trim_words(f"{primary} גיא רופא", 120),
    ]))
    secondary = [item for item in secondary if item and item != primary][:3]
    return {
        "primary_query": primary,
        "secondary_queries": secondary,
        "entity_queries": [canonical_name, "גיא רופא"],
        "intent": intent,
    }


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORDS.findall(unbranded_title(value))
        if len(token) >= 3 and token.casefold() not in _STOP_WORDS
    }


def select_related_publications(
    title: str,
    canonical_url: str,
    campaigns: list[dict],
    *,
    limit: int = 3,
) -> list[dict]:
    """Choose genuinely related, already-published pages on the same host."""
    current_host = urlparse(canonical_url).netloc.lower().removeprefix("www.")
    current_tokens = _tokens(title)
    candidates = []
    seen = set()
    for campaign in campaigns:
        candidate_title = campaign.get("title") or ""
        for destination in campaign.get("destinations", []):
            url = destination.get("url") or ""
            host = urlparse(url).netloc.lower().removeprefix("www.")
            normalized = url.rstrip("/")
            if (
                destination.get("status") != "published"
                or not normalized
                or host != current_host
                or normalized == canonical_url.rstrip("/")
                or normalized in seen
            ):
                continue
            overlap = current_tokens & _tokens(candidate_title)
            if not overlap:
                continue
            seen.add(normalized)
            candidates.append({
                "title": unbranded_title(candidate_title),
                "url": url,
                "score": len(overlap),
            })
    candidates.sort(key=lambda item: (-item["score"], item["title"]))
    return [
        {"title": item["title"], "url": item["url"]}
        for item in candidates[:limit]
    ]


def render_related_links_html(links: list[dict] | None) -> str:
    if not links:
        return ""
    items = "".join(
        '<li><a href="{}">{}</a></li>'.format(
            html.escape(item["url"], quote=True),
            html.escape(item["title"]),
        )
        for item in links
    )
    return (
        '<section class="related-reading"><h2>להמשך קריאה</h2>'
        f"<ul>{items}</ul></section>"
    )


def audit_published_html(
    document: str,
    *,
    expected_url: str,
    canonical_name: str,
    expected_internal_links: list[dict] | None = None,
) -> dict:
    """Check the HTML actually served to Google after a CMS publication."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", document, re.I | re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", title_match.group(1))).strip() \
        if title_match else ""
    normalized_title = title.replace('ד"ר', "ד״ר")
    canonical_match = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        document,
        re.I,
    ) or re.search(
        r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']',
        document,
        re.I,
    )
    canonical = html.unescape(canonical_match.group(1)).strip() if canonical_match else ""
    description_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)',
        document,
        re.I,
    ) or re.search(
        r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+name=["\']description["\']',
        document,
        re.I,
    )
    description = html.unescape(description_match.group(1)).strip() \
        if description_match else ""
    expected_links = [item.get("url") for item in (expected_internal_links or [])]
    checks = {
        "title_present": bool(title),
        "brand_once_in_title": normalized_title.count(canonical_name) == 1,
        "canonical_matches": urls_equivalent(canonical, expected_url),
        "description_present": bool(description),
        "description_not_truncated": not description.endswith((" ו", " ש", " ה", ":")),
        "no_internal_run_slug": not re.search(
            r"(?:pilot|run-\d+|attempt-\d+)", expected_url, re.I
        ),
        "single_document_head": len(re.findall(r"<head(?:\s|>)", document, re.I)) == 1,
        "canonical_person_linked": "https://guyrofe.com/#person" in document,
        "internal_links_present": all(url in document for url in expected_links),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "title": title,
        "canonical": canonical,
        "description": description,
        "errors": [name for name, passed in checks.items() if not passed],
    }
