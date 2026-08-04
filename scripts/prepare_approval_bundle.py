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
from reputation_core.content_routing import (
    assert_cross_domain_original,
    draft_metadata,
    validate_stream_destination,
)
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


def save_image_package(image, *, draft_path: str, output_root: str, title: str):
    """Persist all platform variants and return the signed media metadata."""
    media_root = Path(output_root) / "media"
    media_root.mkdir(parents=True, exist_ok=True)
    stem = stable_slug(Path(draft_path).stem)
    dimensions = {
        "hero": (1600, 900),
        "landscape": (1200, 630),
        "square": (1200, 1200),
        "portrait": (1080, 1350),
    }
    saved_variants = {}
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
    return image_uri, image_alt_text, image_sha256, image_metadata


def publication_site(business: dict, site_key: str | None = None) -> dict:
    if site_key:
        for site in business["sites"]:
            if site.get("key") == site_key:
                if site.get("platform", "wordpress") not in {"wordpress", "wix"}:
                    raise ValueError(f"Unsupported publication site: {site_key}")
                return site
        raise ValueError(f"Unknown publication site key: {site_key}")
    return canonical_site(business)


def canonical_url_for(
    draft_path: Path,
    business: dict,
    client_id: str,
    site_key: str | None = None,
) -> str:
    site = publication_site(business, site_key)
    slug = stable_slug(f"{client_id}-{draft_path.stem}")
    if site.get("platform", "wordpress") == "wix":
        slug = slug[:100].rstrip("-")
        route = str(site.get("post_route") or "post").strip("/")
        return f"{site['base_url'].rstrip('/')}/{route}/{slug}"
    return f"{site['base_url'].rstrip('/')}/{slug}/"


def existing_bundle_matches_draft(draft: Path, output_root: str | Path) -> bool:
    """Allow image-only replacement only for exact bytes already bundled for review."""
    root = Path(output_root)
    try:
        index = json.loads((root / INDEX_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    relative_draft = (
        draft.resolve().relative_to(PROJECT_ROOT).as_posix()
        if draft.resolve().is_relative_to(PROJECT_ROOT)
        else str(draft.resolve())
    )
    for entry in index.get("bundles", []):
        if entry.get("draft_path") != relative_draft:
            continue
        bundle_path = PROJECT_ROOT / str(entry.get("bundle_path") or "")
        try:
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if (
            bundle.get("source_draft") == relative_draft
            and bundle.get("source_draft_sha256") == file_sha256(draft)
        ):
            return True
    return False


def prepare_bundle(
    draft_path: str | Path,
    *,
    output_root: str | Path = DEFAULT_ROOT,
    image_uri: str | None = None,
    image_alt_text: str | None = None,
    image_sha256: str | None = None,
    image_metadata: dict | None = None,
    image_selection_error: str | None = None,
    replace_existing_image_only: bool = False,
    site_key: str | None = None,
    channel_ids: list[str] | None = None,
) -> dict:
    draft = resolve_draft_path(str(draft_path))
    title, content = load_draft(draft)
    client = load_client_profile()
    entity_report = audit_article_entity_contract(content, client)
    exact_existing_bundle = (
        replace_existing_image_only
        and existing_bundle_matches_draft(draft, output_root)
    )
    if not entity_report.passed and not exact_existing_bundle:
        raise ValueError(
            "Draft is not bound to the configured client: "
            + "; ".join(entity_report.errors)
        )
    business = load_business_profile()
    metadata = draft_metadata(draft)
    primary = publication_site(
        business,
        site_key or metadata.get("destination_site_key"),
    )
    routing_metadata = {
        **metadata,
        "legacy_content_audit_passed": primary.get("audit_status") == "passed",
    }
    validate_stream_destination(
        site_key=primary["key"],
        stream=metadata.get("content_stream"),
        metadata=routing_metadata,
    )
    cadence = json.loads(
        (PROJECT_ROOT / "config" / "content_cadence.json").read_text(
            encoding="utf-8"
        )
    )
    fingerprint = assert_cross_domain_original(
        content=content,
        site_key=primary["key"],
        draft_path=draft,
        draft_index_path=PROJECT_ROOT / "content_drafts" / "index.json",
        project_root=PROJECT_ROOT,
        threshold=float(
            cadence["quality_policy"]["near_duplicate_cross_domain_threshold"]
        ),
    )
    canonical_url = canonical_url_for(
        draft,
        business,
        client["client_id"],
        primary["key"],
    )
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
            "owner_provided_default",
        }:
            required_roles = {"hero", "landscape", "square", "portrait"}
            missing_roles = required_roles - set(media["variants"])
            if missing_roles:
                raise ValueError(
                    "Image package is missing variants: "
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

    default_channels = [
        "facebook",
        "linkedin",
        "blogger",
        "pinterest",
        "google_business",
    ]
    selected_channels = list(default_channels if channel_ids is None else channel_ids)
    supported_channels = {
        "facebook",
        "linkedin",
        "instagram",
        "blogger",
        "pinterest",
        "google_business",
    }
    unknown_channels = set(selected_channels) - supported_channels
    if unknown_channels:
        raise ValueError(f"Unsupported scheduled channels: {sorted(unknown_channels)}")
    primary_platform = primary.get("platform", "wordpress")
    approved_slug = stable_slug(f"{client['client_id']}-{draft.stem}")
    if primary_platform == "wix":
        approved_slug = approved_slug[:100].rstrip("-")
    canonical_target_id = (
        "canonical_wix" if primary_platform == "wix" else "canonical_wordpress"
    )
    target_candidates = {
        "canonical": {
            "target_id": canonical_target_id,
            "platform": "Wix" if primary_platform == "wix" else "WordPress",
            "asset": urlparse(primary["base_url"]).netloc,
            "payload": {
                "title": title,
                "markdown": content,
                "canonical_url": canonical_url,
                "site_key": primary["key"],
                "content_stream": metadata.get("content_stream"),
                "content_fingerprint": fingerprint,
                "slug": approved_slug,
                "image": media_variant("hero"),
            },
        },
        "facebook": {
            "target_id": "facebook_page",
            "platform": "Facebook",
            "asset": "configured Facebook Page",
            "payload": {
                "title": title,
                "text": credited_text(variants["facebook"]),
                "link": canonical_url,
                "image": media_variant("landscape"),
                "disclosure": variants["disclosure"],
            },
        },
        "linkedin": {
            "target_id": "linkedin_member",
            "platform": "LinkedIn",
            "asset": "configured LinkedIn member",
            "payload": {
                "title": title,
                "text": credited_text(variants["linkedin"]),
                "link": canonical_url,
                "image": media_variant("landscape"),
                "disclosure": variants["disclosure"],
            },
        },
        "instagram": {
            "target_id": "instagram_business",
            "platform": "Instagram",
            "asset": "configured Instagram professional account",
            "payload": {
                "title": title,
                "text": credited_text(variants["instagram"]),
                "link": canonical_url,
                "image": media_variant("square"),
                "disclosure": variants["disclosure"],
            },
        },
        "blogger": {
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
                "disclosure": variants["disclosure"],
            },
        },
        "pinterest": {
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
                "disclosure": variants["disclosure"],
            },
        },
        "google_business": {
            "target_id": "google_business_profile",
            "platform": "Google Business Profile",
            "asset": "configured verified Google Business location",
            "payload": {
                **variants["google_business"],
                "image": media_variant("landscape"),
                "information_only": True,
                "booking_or_contact_cta": False,
            },
        },
    }
    targets = [target_candidates["canonical"]] + [
        target_candidates[channel] for channel in selected_channels
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
            "instagram_product_publication_scheduled": "instagram" in selected_channels,
            "google_business_information_only": (
                "google_business" in selected_channels
            ),
            "tiktok_product_publication": False,
            "x_publication": False,
            "sources_present": bool(sources),
            "approved_image_required_before_publication": True,
            "approved_image_ready": bool(media),
            "branded_image_variants_ready": bool(
                media
                and {"hero", "landscape", "square", "portrait"}
                <= set((media.get("variants") or {}))
            ),
            "destination_role_validated": True,
            "cross_domain_originality_checked": True,
            "content_fingerprint": fingerprint,
            "secondary_wix_audit_passed": (
                primary.get("audit_status") == "passed"
                if primary["key"] == "GUYROFE_WIX_MEDIA_ARCHIVE"
                else None
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
    parser.add_argument("--site-key")
    parser.add_argument(
        "--channels",
        default=None,
        help="Comma-separated scheduled channels; empty means site only.",
    )
    parser.add_argument(
        "--result-path",
        help="Optionally write the machine-readable result JSON to this path.",
    )
    parser.add_argument(
        "--find-licensed-image",
        action="store_true",
        help="Find and verify a licensed real photograph; nothing is published.",
    )
    parser.add_argument(
        "--replace-existing-image-only",
        action="store_true",
        help=(
            "Keep exact existing draft bytes while replacing media. Allowed only "
            "when a prior bundle contains the same draft hash."
        ),
    )
    args = parser.parse_args()
    image_uri = args.image_uri
    image_alt_text = args.image_alt_text
    image_sha256 = args.image_sha256
    image_metadata = None
    image_selection_error = None
    image = None
    if args.find_licensed_image:
        title, content = load_draft(resolve_draft_path(args.draft_path))
        try:
            image = social_image.generate(title, article_visual_context(content))
        except social_image.PhotoSelectionError as exc:
            image_selection_error = f"{type(exc).__name__}: {exc}"
            image = social_image.default_branded_image()
        except Exception as exc:
            raise RuntimeError(
                "The licensed-photo search failed without creating an AI image: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
    elif not image_uri:
        title, _content = load_draft(resolve_draft_path(args.draft_path))
        image = social_image.default_branded_image()
    if image is not None:
        image_uri, image_alt_text, image_sha256, image_metadata = save_image_package(
            image,
            draft_path=args.draft_path,
            output_root=args.output_root,
            title=title,
        )
    result = prepare_bundle(
        args.draft_path,
        output_root=args.output_root,
        image_uri=image_uri,
        image_alt_text=image_alt_text,
        image_sha256=image_sha256,
        image_metadata=image_metadata,
        image_selection_error=image_selection_error,
        replace_existing_image_only=args.replace_existing_image_only,
        site_key=args.site_key,
        channel_ids=(
            [item.strip() for item in args.channels.split(",") if item.strip()]
            if args.channels is not None
            else None
        ),
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
