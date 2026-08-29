"""Deterministic, single-tenant entity binding for every public content asset."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EntityContext:
    client_id: str
    canonical_name: str
    name_variants: tuple[str, ...]
    canonical_site: str
    profile_url: str
    current_role: str
    public_status: str
    primary_query: str


@dataclass(frozen=True)
class EntityContractReport:
    passed: bool
    checks: dict[str, bool]
    errors: tuple[str, ...]
    canonical_name_mentions: int


def build_entity_context(profile: dict) -> EntityContext:
    facts = profile["canonical_facts"]
    primary_queries = profile["search_goal"]["primary_queries"]
    canonical_site = facts["canonical_site"].rstrip("/")
    return EntityContext(
        client_id=profile["client_id"],
        canonical_name=facts["primary_name"],
        name_variants=tuple(
            dict.fromkeys([facts["primary_name"], *facts.get("name_variants", [])])
        ),
        canonical_site=canonical_site,
        profile_url=(facts.get("profile_url") or f"{canonical_site}/profile/"),
        current_role=facts["current_role"],
        public_status=facts["public_status_he"],
        primary_query=primary_queries[0]["query"],
    )


def _name_pattern(context: EntityContext) -> re.Pattern:
    variants = sorted(context.name_variants, key=len, reverse=True)
    return re.compile("|".join(re.escape(item) for item in variants))


def title_with_entity(title: str, context: EntityContext) -> str:
    """Return one concise title containing the canonical entity exactly once."""
    clean = " ".join((title or "").lstrip("#").split()).strip(" |–—-")
    clean = _name_pattern(context).sub(context.canonical_name, clean)
    clean = re.sub(
        rf"(?:\s*[|–—-]\s*{re.escape(context.canonical_name)})+",
        f" | {context.canonical_name}",
        clean,
    )
    suffix = f" | {context.canonical_name}"
    if context.canonical_name not in clean:
        clean = clean[: 180 - len(suffix)].rstrip(" |–—-") + suffix
    if clean.count(context.canonical_name) > 1:
        first, *rest = clean.split(context.canonical_name)
        clean = first + context.canonical_name + "".join(rest).replace(
            context.canonical_name, ""
        )
    return clean[:180].strip()


def visible_byline(context: EntityContext) -> str:
    return f"מאת [{context.canonical_name}]({context.profile_url})"


def author_box(context: EntityContext) -> str:
    return "\n".join(
        [
            "## על המחבר",
            "",
            f"**{context.canonical_name}** — {context.current_role}.",
            "",
            context.public_status,
            "",
            f"[לפרופיל הרשמי של {context.canonical_name}]({context.profile_url})",
        ]
    )


def _looks_like_byline(line: str, context: EntityContext) -> bool:
    stripped = (line or "").strip()
    begins_with_by = bool(re.match(r"^[\[*_]*מאת(?:\s|\])", stripped))
    names_client = any(variant in stripped for variant in context.name_variants)
    return begins_with_by and names_client


def _article_body(markdown: str, context: EntityContext) -> str:
    """Return editorial body only, excluding branded furniture and sources."""
    body = re.sub(r"^#\s+.+$", "", markdown or "", count=1, flags=re.MULTILINE)
    body = "\n".join(
        line for line in body.splitlines() if not _looks_like_byline(line, context)
    )
    body = re.split(r"^##\s+על המחבר\s*$", body, maxsplit=1, flags=re.MULTILINE)[0]
    body = re.split(r"^##\s+מקורות\s*$", body, maxsplit=1, flags=re.MULTILINE)[0]
    return body.strip()


def apply_article_contract(markdown: str, profile: dict) -> str:
    """Bind a generated draft to the configured client without adding new facts."""
    context = build_entity_context(profile)
    text = (markdown or "").strip()
    lines = text.splitlines()
    h1_index = next(
        (index for index, line in enumerate(lines) if re.match(r"^#\s+\S", line)),
        None,
    )
    if h1_index is None:
        return text
    lines[h1_index] = "# " + title_with_entity(lines[h1_index], context)
    first_h2 = next(
        (index for index, line in enumerate(lines) if re.match(r"^##\s+\S", line)),
        len(lines),
    )
    lines = [
        line
        for index, line in enumerate(lines)
        if index >= first_h2 or not _looks_like_byline(line, context)
    ]
    h1_index = next(
        index for index, line in enumerate(lines) if re.match(r"^#\s+\S", line)
    )
    lines[h1_index + 1 : h1_index + 1] = ["", visible_byline(context)]
    text = "\n".join(lines).strip()

    if context.canonical_name not in _article_body(text, context):
        byline = visible_byline(context)
        branded_sentence = (
            f"המאמר הוכן עבור מאגר המידע של {context.canonical_name} "
            "ומציג מידע כללי המבוסס על מקורות."
        )
        parts = text.splitlines()
        byline_index = parts.index(byline)
        paragraph_start = byline_index + 1
        while paragraph_start < len(parts) and not parts[paragraph_start].strip():
            paragraph_start += 1
        paragraph_end = paragraph_start
        while (
            paragraph_end < len(parts)
            and parts[paragraph_end].strip()
            and not parts[paragraph_end].startswith("## ")
        ):
            paragraph_end += 1
        parts[paragraph_end:paragraph_end] = ["", branded_sentence]
        text = "\n".join(parts).strip()

    text = re.sub(
        r"^##\s+על המחבר\s*$.*?(?=^##\s+מקורות\s*$|\Z)",
        "",
        text,
        flags=re.MULTILINE | re.DOTALL,
    ).strip()
    # Keep the truthful current-status note as the final readable section,
    # after the article and its source links.
    text = text.rstrip() + "\n\n" + author_box(context)
    return text.strip()


def audit_article_entity_contract(markdown: str, profile: dict) -> EntityContractReport:
    context = build_entity_context(profile)
    title = next(
        (
            line.removeprefix("#").strip()
            for line in (markdown or "").splitlines()
            if re.match(r"^#\s+\S", line)
        ),
        "",
    )
    canonical_mentions = (markdown or "").count(context.canonical_name)
    body_mentions = _article_body(markdown, context).count(context.canonical_name)
    byline_lines = [
        line
        for line in (markdown or "").splitlines()
        if _looks_like_byline(line, context)
    ]
    checks = {
        "canonical_name_once_in_title": title.count(context.canonical_name) == 1,
        "linked_visible_byline": byline_lines == [visible_byline(context)],
        "author_box": bool(
            re.search(r"^##\s+על המחבר\s*$", markdown or "", re.MULTILINE)
        ),
        "linked_profile": (markdown or "").count(context.profile_url) >= 2,
        "current_role_visible": context.current_role in (markdown or ""),
        "status_truthful": context.public_status in (markdown or ""),
        "body_entity_frequency": 1 <= body_mentions <= 4,
        "natural_entity_frequency": 3 <= canonical_mentions <= 8,
    }
    messages = {
        "canonical_name_once_in_title": "canonical client name must appear once in H1",
        "linked_visible_byline": "linked visible client byline is required",
        "author_box": "client author box is required",
        "linked_profile": "byline and author box must link to the official profile",
        "current_role_visible": "approved current role is required",
        "status_truthful": "approved current-practice status is required",
        "body_entity_frequency": "client name must appear naturally in the article body",
        "natural_entity_frequency": "client name frequency must remain natural",
    }
    errors = tuple(messages[key] for key, passed in checks.items() if not passed)
    return EntityContractReport(
        passed=all(checks.values()),
        checks=checks,
        errors=errors,
        canonical_name_mentions=canonical_mentions,
    )


def meta_description(markdown: str, profile: dict, *, max_length: int = 170) -> str:
    context = build_entity_context(profile)
    body = re.sub(r"^#\s+.+$", "", markdown or "", count=1, flags=re.MULTILINE)
    body = re.sub(r"^מאת\s+\[.+?\]\(.+?\)\s*$", "", body, flags=re.MULTILINE)
    first = next(
        (
            re.sub(r"[*_`>\[\]#]", "", block).strip()
            for block in re.split(r"\n\s*\n", body)
            if block.strip() and not block.lstrip().startswith("#")
        ),
        "",
    )
    description = " ".join(f"{context.canonical_name}: {first}".split()).strip()
    if len(description) <= max_length:
        return description
    sentences = re.split(r"(?<=[.!?])\s+", description)
    complete = []
    for sentence in sentences:
        candidate = " ".join([*complete, sentence]).strip()
        if len(candidate) > max_length:
            break
        complete.append(sentence)
    if complete:
        return " ".join(complete).rstrip()
    shortened = description[:max_length].rsplit(" ", 1)[0]
    shortened = shortened[: max_length - 1]
    return shortened.rstrip(" ,:;–—-") + "…"
