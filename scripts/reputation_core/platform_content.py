"""Create platform-native variants from one approved source without new facts."""
from __future__ import annotations

import re


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#*_>`]", "", value or "")).strip()


def _sentences(markdown: str) -> list[str]:
    plain = _clean(re.sub(r"https?://\S+", "", markdown))
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?׃])\s+", plain)
        if len(item.strip()) > 25
    ]


def build_platform_variants(title: str, markdown: str, canonical_url: str) -> dict:
    """Deterministic transformations; facts remain bounded to approved content."""
    sentences = _sentences(markdown)
    lead = sentences[0] if sentences else _clean(title)
    detail = sentences[1] if len(sentences) > 1 else ""
    bullets = sentences[1:4] or [lead]
    return {
        "facebook": f"{lead}\n\n{detail}".strip(),
        "linkedin": (
            f"{lead}\n\n" + "\n".join(f"• {item}" for item in bullets)
        ),
        "pinterest": {
            "title": _clean(title)[:100],
            "description": f"{lead} {detail}".strip()[:500],
        },
        "blogger": (
            f"<h2>{_clean(title)}</h2><p>{lead}</p>"
            + (f"<p>{detail}</p>" if detail else "")
        ),
        "google_business": f"{lead}\n\nלמידע נוסף: {canonical_url}"[:1500],
    }


def variants_are_distinct(variants: dict) -> bool:
    texts = []
    for value in variants.values():
        if isinstance(value, dict):
            value = " ".join(str(part) for part in value.values())
        texts.append(_clean(str(value)))
    return len(set(texts)) == len(texts)
