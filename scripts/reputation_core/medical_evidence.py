"""Fail-closed claim-to-source review support for medical articles."""
from __future__ import annotations

import re
from urllib.parse import urlparse


LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
MEDICAL_CLAIM = re.compile(
    r"(?:מחקר|הנחיות|מומלץ|עלול|עשוי|סיכון|יעילות|בטיחות|אבחון|טיפול|"
    r"בדיקה|תסמין|גורם|שכיחות|אחוז|מינון|שבוע|חודש|מטופל|נשים|הריון|"
    r"study|guideline|risk|diagnos|treat|effective|safe|percent)",
    re.IGNORECASE,
)
DATE = re.compile(r"\b(?:19|20)\d{2}\b")


def _body_before_sources(markdown: str) -> str:
    return re.split(
        r"^##\s+מקורות\s*$", markdown or "", maxsplit=1, flags=re.MULTILINE
    )[0]


def _sentences(value: str) -> list[str]:
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?׃])\s+|\n+", value)
        if item.strip() and not item.lstrip().startswith("#")
    ]


def audit_medical_claim_sources(markdown: str) -> dict:
    """Map material medical claims to inline sources at editorial-section level."""
    body = _body_before_sources(markdown)
    mappings = []
    unsupported = []
    sources = {}
    sections = re.split(r"(?=^##\s+)", body, flags=re.MULTILINE)
    for section in sections:
        heading_match = re.search(r"^##\s+(.+)$", section, flags=re.MULTILINE)
        heading = heading_match.group(1).strip() if heading_match else "פתיחה"
        links = LINK.findall(section)
        urls = list(dict.fromkeys(url.rstrip(".,;:") for _anchor, url in links))
        clean = LINK.sub(lambda match: match.group(1), section)
        claims = [sentence for sentence in _sentences(clean) if MEDICAL_CLAIM.search(sentence)]
        for url in urls:
            sources.setdefault(url, {
                "url": url,
                "host": urlparse(url).netloc.lower().removeprefix("www."),
                "year_markers": sorted(set(DATE.findall(section))),
            })
        for claim in claims:
            item = {"section": heading, "claim": claim[:500], "source_urls": urls}
            mappings.append(item)
            if not urls:
                unsupported.append({"section": heading, "claim": claim[:500]})
    return {
        "status": "pass" if not unsupported else "review_required",
        "ready_for_medical_approval": not unsupported,
        "claim_count": len(mappings),
        "supported_claim_count": len(mappings) - len(unsupported),
        "unsupported_claims": unsupported,
        "claim_source_matrix": mappings,
        "sources": list(sources.values()),
        "review_rule": (
            "Every section containing material medical claims must contain a direct inline "
            "citation; a sources list alone is insufficient. Human review remains required."
        ),
    }
