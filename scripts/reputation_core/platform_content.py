"""Create platform-native variants from one approved source without new facts."""
from __future__ import annotations

import re

from .entity_contract import build_entity_context, title_with_entity
from .strategy import load_client_profile


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[#*_>`]", "", value or "")).strip()


def _sentences(markdown: str) -> list[str]:
    body = re.sub(r"^#\s+.+$", "", markdown or "", count=1, flags=re.MULTILINE)
    body = re.sub(
        r"^מאת\s+\[.+?\]\(.+?\)\s*$",
        "",
        body,
        flags=re.MULTILINE,
    )
    body = re.split(r"^##\s+(?:על המחבר|מקורות)\s*$", body, maxsplit=1, flags=re.MULTILINE)[0]
    plain = _clean(re.sub(r"https?://\S+", "", body))
    return [
        item.strip()
        for item in re.split(r"(?<=[.!?׃])\s+", plain)
        if len(item.strip()) > 25
    ]


def build_platform_variants(
    title: str,
    markdown: str,
    canonical_url: str,
    profile: dict | None = None,
) -> dict:
    """Deterministic transformations; facts remain bounded to approved content."""
    context = build_entity_context(profile or load_client_profile())
    branded_title = title_with_entity(title, context)
    signature = f"מאת {context.canonical_name}"
    sentences = _sentences(markdown)
    lead = sentences[0] if sentences else _clean(title)
    detail = sentences[1] if len(sentences) > 1 else ""
    bullets = sentences[1:4] or [lead]
    return {
        "facebook": f"{lead}\n\n{detail}\n\n{signature}".strip(),
        "linkedin": (
            f"{lead}\n\n"
            + "\n".join(f"• {item}" for item in bullets)
            + f"\n\n{signature}"
        ),
        "instagram": (
            f"נקודה רפואית שכדאי להכיר:\n\n{lead}\n\n"
            + "\n".join(f"{index}. {item}" for index, item in enumerate(bullets[:3], 1))
            + f"\n\n{signature}"
        )[:1900],
        "pinterest": {
            "title": _clean(branded_title)[:100],
            "description": f"{lead} {detail} {signature}".strip()[:500],
        },
        "blogger": (
            f"<h2>{_clean(branded_title)}</h2><p>{signature}</p><p>{lead}</p>"
            + (f"<p>{detail}</p>" if detail else "")
        ),
    }


def variants_are_distinct(variants: dict) -> bool:
    texts = []
    for value in variants.values():
        if isinstance(value, dict):
            value = " ".join(str(part) for part in value.values())
        texts.append(_clean(str(value)))
    return len(set(texts)) == len(texts)
