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
from reputation_core.entity_contract import audit_article_entity_contract
from reputation_core.platform_content import build_platform_variants
import social_image


DEFAULT_ROOT = PROJECT_ROOT / "approval_bundles"
INDEX_NAME = "index.json"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def article_visual_context(content: str) -> str:
    """Keep enough article substance to select a topic-specific real photo."""
    without_sources = content.split("\n## מקורות", 1)[0]
    plain = " ".join(
        line.lstrip("#-* ").strip()
        for line in without_sources.splitlines()
        if line.strip() and not line.lstrip().startswith("http")
    )
    return " ".join(plain.split())[:2400]


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
    image_metadata: dict | None = None,
    image_selection_error: str | None = None,
) -> dict:
    draft = resolve_draft_path(str(draft_path))
    title, content = load_draft(draft)
    client = load_client_profile()
    entity_report = audit_article_entity_contract(content, client)
    if not entity_report.passed:
        raise ValueError(
            "Draft is not bound to the configured client: "
            + "; ".join(entity_report.errors)
        )
    business = load_business_profile()
    canonical_url = canonical_url_for(draft, business, client["client_id"])
    variants = build_platform_variants(title, content, canonical_url)
    primary_query = client["search_goal"]["primary_queries"][0]["query"]
    sources = [{"url": url, "type": "citation"} for url in extract_citation_urls(content)]
    media = None
    if image_uri:
        image_metadata = image_metadata or {}
        media = {
            "uri": image_uri,
            "sha256": image_sha256,
            "alt_text": image_alt_text or social_image.alt_text(title),
            "visual_description": image_metadata.get(
                "visual_description", social_image.visual_description(title)
            ),
            "source_type": image_metadata.get("source_type", "manual"),
            "source_page_url": image_metadata.get("source_page_url", ""),
            "source_image_url": image_metadata.get("source_image_url", ""),
            "creator": image_metadata.get("creator", ""),
            "license_name": image_metadata.get("license_name", ""),
            "license_url": image_metadata.get("license_url", ""),
            "attribution": image_metadata.get("attribution", ""),
            "generation_model": image_metadata.get("generation_model", ""),
            "generation_prompt": image_metadata.get("generation_prompt", ""),
            "variants": image_metadata.get("variants", {}),
            "must_match_approved_bytes_when_local": True,
        }
        if media["source_type"] in {
            "wikimedia_commons_licensed_photo",
            "openai_generated_text_free_visual",
            "deterministic_text_free_fallback",
        }:
            required_roles = {"hero", "landscape", "square", "portrait"}
            missing_roles = required_roles - set(media["variants"])
            if missing_roles:
                raise ValueError(
                    "Text-free image package is missing variants: "
                    + ", ".join(sorted(missing_roles))
                )
            if (media["alt_text"] or "").count(
                client["canonical_facts"]["primary_name"]
            ) != 1:
                raise ValueError(
                    "Image alt text must name the configured client once"
                )
    credit = (
        (media or {}).get("attribution", "").strip()
        if (media or {}).get("license_name")
        else ""
    )

    def media_variant(role: str) -> dict | None:
        if not media:
            return None
        variant = (media.get("variants") or {}).get(role)
        if not variant:
            return media
        return {**media, **variant, "role": role}

    def credited_text(value: str) -> str:
        return f"{value.rstrip()}\n\nקרדיט תמונה: {credit}" if credit else value

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
                "image": media_variant("hero"),
            },
        },
        {
            "target_id": "facebook_page",
            "platform": "Facebook",
            "asset": "configured Facebook Page",
            "payload": {
                "title": title,
                "text": credited_text(variants["facebook"]),
                "link": canonical_url,
                "image": media_variant("landscape"),
            },
        },
        {
            "target_id": "linkedin_member",
            "platform": "LinkedIn",
            "asset": "configured LinkedIn member",
            "payload": {
                "title": title,
                "text": credited_text(variants["linkedin"]),
                "link": canonical_url,
                "image": media_variant("landscape"),
            },
        },
        {
            "target_id": "blogger_blog",
            "platform": "Blogger",
            "asset": "configured Blogger blog",
            "payload": {
                "title": title,
                "html": (
                    variants["blogger"]
                    + (
                        f"\n<p><small>קרדיט תמונה: {credit}</small></p>"
                        if credit
                        else ""
                    )
                ),
                "link": canonical_url,
                "image": media_variant("hero"),
            },
        },
        {
            "target_id": "pinterest_board",
            "platform": "Pinterest",
            "asset": "configured public Pinterest board",
            "payload": {
                **variants["pinterest"],
                "description": credited_text(variants["pinterest"]["description"])[
                    :500
                ],
                "link": canonical_url,
                "image": media_variant("portrait"),
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
            "approved_image_required_before_publication": True,
            "approved_image_ready": bool(media),
            "branded_image_variants_ready": bool(
                media
                and {"hero", "landscape", "square", "portrait"}
                <= set((media.get("variants") or {}))
            ),
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
    index_path = root / INDEX_NAME
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        index = {"version": 7, "bundles": []}
    entry = {
        "approval_id": bundle["approval_id"],
        "draft_path": relative_draft,
        "bundle_path": json_path.relative_to(PROJECT_ROOT).as_posix(),
        "preview_path": preview_path.relative_to(PROJECT_ROOT).as_posix(),
        "created_at": bundle["created_at"],
        "required_approval_scopes": bundle["required_approval_scopes"],
        "image_status": "ready" if media else "awaiting_replacement",
        "image_selection_error": image_selection_error,
    }
    index["version"] = 7
    index["bundles"] = [
        existing
        for existing in index.get("bundles", [])
        if existing.get("draft_path") != relative_draft
    ]
    index["bundles"].append(entry)
    index["bundles"].sort(key=lambda item: item.get("created_at", ""), reverse=True)
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "approval_id": bundle["approval_id"],
        "bundle_path": str(json_path),
        "preview_path": str(preview_path),
        "index_path": str(index_path),
        "required_approval_scopes": bundle["required_approval_scopes"],
        "image_status": entry["image_status"],
        "image_selection_error": image_selection_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft_path")
    parser.add_argument("--output-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--image-uri")
    parser.add_argument("--image-alt-text")
    parser.add_argument("--image-sha256")
    parser.add_argument(
        "--result-path",
        help="Optionally write the machine-readable result JSON to this path.",
    )
    parser.add_argument(
        "--generate-image",
        action="store_true",
        help="Generate the complete branded review-image package; nothing is published.",
    )
    args = parser.parse_args()
    image_uri = args.image_uri
    image_alt_text = args.image_alt_text
    image_sha256 = args.image_sha256
    image_metadata = None
    image_selection_error = None
    if args.generate_image:
        title, content = load_draft(resolve_draft_path(args.draft_path))
        try:
            image = social_image.generate(title, article_visual_context(content))
        except Exception as exc:
            raise RuntimeError(
                "The guaranteed image pipeline failed before producing its "
                f"deterministic fallback: {type(exc).__name__}: {exc}"
            ) from exc
        media_root = Path(args.output_root) / "media"
        media_root.mkdir(parents=True, exist_ok=True)
        stem = stable_slug(Path(args.draft_path).stem)
        saved_variants = {}
        dimensions = {
            "hero": (1600, 900),
            "landscape": (1200, 630),
            "square": (1200, 1200),
            "portrait": (1080, 1350),
        }
        for role, content_bytes in image.variants.items():
            variant_path = media_root / f"{stem}-{role}.png"
            variant_path.write_bytes(content_bytes)
            saved_variants[role] = {
                "uri": variant_path.relative_to(PROJECT_ROOT).as_posix(),
                "sha256": file_sha256(variant_path),
                "width": dimensions[role][0],
                "height": dimensions[role][1],
            }
        media_path = media_root / f"{stem}-landscape.png"
        image_uri = media_path.relative_to(PROJECT_ROOT).as_posix()
        image_alt_text = social_image.alt_text(
            title,
            image.visual_description,
            entity_relevant=True,
        )
        image_sha256 = file_sha256(media_path)
        image_metadata = {
            "visual_description": image.visual_description,
            "source_type": image.source_type,
            "source_page_url": image.source_page_url,
            "source_image_url": image.source_image_url,
            "creator": image.creator,
            "license_name": image.license_name,
            "license_url": image.license_url,
            "attribution": image.attribution,
            "generation_model": image.generation_model,
            "generation_prompt": image.generation_prompt,
            "variants": saved_variants,
        }
    result = prepare_bundle(
        args.draft_path,
        output_root=args.output_root,
        image_uri=image_uri,
        image_alt_text=image_alt_text,
        image_sha256=image_sha256,
        image_metadata=image_metadata,
        image_selection_error=image_selection_error,
    )
    if args.result_path:
        result_path = Path(args.result_path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
