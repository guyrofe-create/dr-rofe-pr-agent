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
TRUSTED_MEDICAL_SOURCE_DOMAINS = frozenset(
    {
        "who.int",
        "cdc.gov",
        "nih.gov",
        "ncbi.nlm.nih.gov",
        "medlineplus.gov",
        "fda.gov",
        "nhs.uk",
        "nice.org.uk",
        "gov.il",
        "health.gov.il",
        "acog.org",
        "rcog.org.uk",
        "figo.org",
        "asrm.org",
        "eshre.eu",
        "menopause.org",
        "ema.europa.eu",
        "ecdc.europa.eu",
        "cochranelibrary.com",
        "doi.org",
    }
)


def _body_before_sources(markdown: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", "", markdown or "", flags=re.DOTALL)
    return re.split(
        r"^##\s+מקורות\s*$", without_comments, maxsplit=1, flags=re.MULTILINE
    )[0]


def _trusted_medical_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in TRUSTED_MEDICAL_SOURCE_DOMAINS
    )


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
    # The rule is deliberately scoped to H2 editorial sections. Front matter,
    # the H1, byline and author-profile link are identity metadata, not medical
    # evidence and must never be counted as claims or supporting sources.
    sections = [
        section
        for section in re.split(r"(?=^##\s+)", body, flags=re.MULTILINE)
        if re.match(r"^##\s+", section)
    ]
    for section in sections:
        heading_match = re.search(r"^##\s+(.+)$", section, flags=re.MULTILINE)
        heading = heading_match.group(1).strip() if heading_match else "פתיחה"
        links = LINK.findall(section)
        urls = list(dict.fromkeys(
            url.rstrip(".,;:")
            for _anchor, url in links
            if _trusted_medical_url(url)
        ))
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
