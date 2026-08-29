#!/usr/bin/env python3
"""Prepare an exact P7 bundle for safe legacy WordPress SEO corrections."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from daily_run import load_draft
from reputation_core.approval_workflow import build_bundle, render_preview
from reputation_core.entity_contract import meta_description
from reputation_core.publication_seo import unbranded_title, wordpress_public_slug
from reputation_core.strategy import load_client_profile
from campaign_run import public_slug


def _target_id(url: str) -> str:
    return "legacy_seo_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def build_legacy_bundle() -> tuple[dict, list[dict]]:
    profile = load_client_profile()
    campaigns = json.loads(
        (ROOT / "content_drafts" / "campaigns" / "index.json").read_text(
            encoding="utf-8"
        )
    ).get("campaigns", [])
    targets = []
    excluded = []
    new_slugs = set()
    for campaign in campaigns:
        title = campaign.get("title") or ""
        draft_value = campaign.get("draft") or ""
        draft_path = ROOT / draft_value
        for destination in campaign.get("destinations", []):
            old_url = destination.get("url") or ""
            parsed = urlparse(old_url)
            if (
                destination.get("status") != "published"
                or "pilot" not in parsed.path
            ):
                continue
            if parsed.netloc.lower().removeprefix("www.") != "drguyrofe.co.il":
                excluded.append({
                    "url": old_url,
                    "title": title,
                    "reason": (
                        "manual_consolidation_required"
                        if parsed.netloc.lower().removeprefix("www.") == "guyrofe.com"
                        else "wix_update_requires_separate_provider_path"
                    ),
                })
                continue
            try:
                draft_title, content = load_draft(draft_path)
            except (OSError, ValueError):
                excluded.append({
                    "url": old_url,
                    "title": title,
                    "reason": "source_draft_unavailable",
                })
                continue
            new_title = unbranded_title(draft_title)
            new_slug = wordpress_public_slug(draft_title)
            if new_slug in new_slugs:
                excluded.append({
                    "url": old_url,
                    "title": title,
                    "reason": "duplicate_clean_slug_requires_consolidation",
                })
                continue
            new_slugs.add(new_slug)
            old_slug = parsed.path.strip("/")
            new_url = f"https://www.drguyrofe.co.il/{new_slug}/"
            targets.append({
                "target_id": _target_id(old_url),
                "platform": "WordPress SEO remediation",
                "asset": old_url,
                "payload": {
                    "site_key": "DRGUYROFE_CO_IL",
                    "old_url": old_url,
                    "old_slug": old_slug,
                    "expected_current_title": draft_title,
                    "new_title": new_title,
                    "new_slug": new_slug,
                    "expected_new_url": new_url,
                    "meta_description": meta_description(content, profile),
                    "changes": [
                        "remove_duplicate_brand_suffix_from_cms_title",
                        "replace_internal_pilot_slug_with_readable_topic_slug",
                        "replace_truncated_excerpt_with_complete_description",
                    ],
                },
            })
    bundle = build_bundle(
        action_type="legacy_wordpress_seo_remediation",
        objective=(
            "Correct exact legacy health-news URLs, titles and descriptions without "
            "changing article content or touching duplicate evergreen articles."
        ),
        query="ד״ר גיא רופא",
        targets=targets,
        sources=[{"url": target["asset"], "type": "existing_publication"}
                 for target in targets],
        sensitive_actions=["medical_content"],
        risk={
            "level": "medium",
            "score": 5,
            "notes": [
                "Every target is an existing unique health-news post.",
                "The apply step aborts on title mismatch or slug collision.",
                "Evergreen duplicates and Wix posts are excluded.",
            ],
        },
        compliance={
            "exact_existing_post_required": True,
            "abort_on_slug_collision": True,
            "article_body_change_prohibited": True,
            "duplicate_evergreen_change_prohibited": True,
            "redirect_verification_required": True,
        },
    )
    return bundle, excluded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "approval_bundles")
    parser.add_argument(
        "--exclusions-output",
        type=Path,
        default=ROOT / "data" / "legacy_seo_remediation_exclusions.json",
    )
    args = parser.parse_args()
    bundle, excluded = build_legacy_bundle()
    args.output_root.mkdir(parents=True, exist_ok=True)
    bundle_path = args.output_root / f"{bundle['approval_id']}.json"
    preview_path = args.output_root / f"{bundle['approval_id']}.html"
    bundle_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    preview_path.write_text(render_preview(bundle), encoding="utf-8")
    args.exclusions_output.write_text(
        json.dumps({"version": 1, "excluded": excluded}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "approval_id": bundle["approval_id"],
        "bundle_path": str(bundle_path),
        "preview_path": str(preview_path),
        "targets": len(bundle["targets"]),
        "excluded": len(excluded),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
