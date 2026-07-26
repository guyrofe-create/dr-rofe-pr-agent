#!/usr/bin/env python3
"""Prepare one exact P7 review bundle and HTML preview; never publish."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))

from campaign_run import (
    PROJECT_ROOT,
    canonical_site,
    first_paragraph,
    load_business_profile,
    stable_slug,
)
from daily_run import load_draft, resolve_draft_path
from reputation_core import load_client_profile
from reputation_core.approval_workflow import build_bundle, render_preview
from reputation_core.entity_seo import extract_citation_urls
from reputation_core.platform_content import build_platform_variants
import social_image


DEFAULT_ROOT = PROJECT_ROOT / "approval_bundles"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_url_for(draft_path: Path, business: dict, client_id: str) -> str:
    site = canonical_site(business)
    slug = stable_slug(f"{client_id}-{draft_path.stem}")
    return f"{site['base_url'].rstrip('/')}/{slug}/"


def prepare_bundle(
    draft_path: str | Path,
    *,
    output_root: str | Path = DEFAULT_ROOT,
    image_uri: str | None = None,
    image_alt_text: str | None = None,
    image_sha256: str | None = None,
) -> dict:
    draft = resolve_draft_path(str(draft_path))
    title, content = load_draft(draft)
    client = load_client_profile()
    business = load_business_profile()
    canonical_url = canonical_url_for(draft, business, client["client_id"])
    variants = build_platform_variants(title, content, canonical_url)
    primary_query = client["search_goal"]["primary_queries"][0]["query"]
    sources = [{"url": url, "type": "citation"} for url in extract_citation_urls(content)]
    media = None
    if image_uri:
        media = {
            "uri": image_uri,
            "sha256": image_sha256,
            "alt_text": image_alt_text or social_image.alt_text(title),
            "visual_description": social_image.visual_description(title),
            "must_match_approved_bytes_when_local": True,
        }

    primary = canonical_site(business)
    targets = [
        {
            "target_id": "canonical_wordpress",
            "platform": "WordPress",
            "asset": urlparse(primary["base_url"]).netloc,
            "payload": {
                "title": title,
                "markdown": content,
                "canonical_url": canonical_url,
                "slug": stable_slug(f"{client['client_id']}-{draft.stem}"),
                "image": media,
            },
        },
        {
            "target_id": "facebook_page",
            "platform": "Facebook",
            "asset": "configured Facebook Page",
            "payload": {
                "title": title,
                "text": variants["facebook"],
                "link": canonical_url,
                "image": media,
            },
        },
        {
            "target_id": "linkedin_member",
            "platform": "LinkedIn",
            "asset": "configured LinkedIn member",
            "payload": {
                "title": title,
                "text": variants["linkedin"],
                "link": canonical_url,
                "image": media,
            },
        },
        {
            "target_id": "blogger_blog",
            "platform": "Blogger",
            "asset": "configured Blogger blog",
            "payload": {
                "title": title,
                "html": variants["blogger"],
                "link": canonical_url,
                "image": media,
            },
        },
        {
            "target_id": "pinterest_board",
            "platform": "Pinterest",
            "asset": "configured public Pinterest board",
            "payload": {
                **variants["pinterest"],
                "link": canonical_url,
                "image": media,
            },
        },
    ]
    relative_draft = (
        draft.resolve().relative_to(PROJECT_ROOT).as_posix()
        if draft.resolve().is_relative_to(PROJECT_ROOT)
        else str(draft.resolve())
    )
    medical = bool(client.get("content_plan", {}).get("medical_content"))
    bundle = build_bundle(
        action_type="coordinated_owned_media_publication",
        objective=client["search_goal"]["statement"],
        query=primary_query,
        targets=targets,
        sources=sources,
        media=media,
        sensitive_actions=["medical_content"] if medical else [],
        source_draft=relative_draft,
        source_draft_sha256=file_sha256(draft),
        risk={
            "level": "medium" if medical else "low",
            "score": 5 if medical else 2,
            "notes": [
                "Medical information requires explicit medical-content approval."
                if medical
                else "General informational publication.",
                "Each destination must publish only its exact approved payload.",
            ],
        },
        compliance={
            "medical_review_required": medical,
            "no_consultation_invitation": True,
            "no_current_practice_implication": True,
            "instagram_and_tiktok_product_publication": False,
            "x_publication": False,
            "sources_present": bool(sources),
        },
    )
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / f"{bundle['approval_id']}.json"
    preview_path = root / f"{bundle['approval_id']}.html"
    json_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    preview_path.write_text(render_preview(bundle), encoding="utf-8")
    return {
        "approval_id": bundle["approval_id"],
        "bundle_path": str(json_path),
        "preview_path": str(preview_path),
        "required_approval_scopes": bundle["required_approval_scopes"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft_path")
    parser.add_argument("--output-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--image-uri")
    parser.add_argument("--image-alt-text")
    parser.add_argument("--image-sha256")
    args = parser.parse_args()
    result = prepare_bundle(
        args.draft_path,
        output_root=args.output_root,
        image_uri=args.image_uri,
        image_alt_text=args.image_alt_text,
        image_sha256=args.image_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
