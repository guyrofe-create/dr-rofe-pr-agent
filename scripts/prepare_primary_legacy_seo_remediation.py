#!/usr/bin/env python3
"""Prepare the exact P7 bundle for selected primary-site SEO winners."""
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


def build_primary_bundle() -> dict:
    profile = load_client_profile()
    selection = json.loads(
        (ROOT / "data" / "primary_legacy_seo_selection.json").read_text(
            encoding="utf-8"
        )
    )
    targets = []
    for item in selection["selected"]:
        old_url = item["url"]
        parsed = urlparse(old_url)
        draft_title, content = load_draft(ROOT / item["draft"])
        new_title = unbranded_title(draft_title)
        new_slug = wordpress_public_slug(new_title)
        targets.append({
            "target_id": "primary_seo_" + hashlib.sha256(
                old_url.encode("utf-8")
            ).hexdigest()[:16],
            "platform": "Primary WordPress SEO remediation",
            "asset": old_url,
            "payload": {
                "site_key": "GUYROFE_COM",
                "old_url": old_url,
                "old_slug": parsed.path.strip("/"),
                "expected_current_title": draft_title,
                "new_title": new_title,
                "new_slug": new_slug,
                "expected_new_url": f"https://guyrofe.com/{new_slug}/",
                "meta_description": item.get("meta_description") or meta_description(
                    content, profile
                ),
                "selection_reason": item["reason"],
                "changes": [
                    "remove_duplicate_brand_suffix_from_cms_title",
                    "replace_internal_pilot_slug_with_readable_topic_slug",
                    "replace_excerpt_with_complete_description",
                ],
            },
        })
    return build_bundle(
        action_type="legacy_wordpress_seo_remediation",
        objective="Clean exact Search Console-selected primary-site canonical winners.",
        query="ד״ר גיא רופא",
        targets=targets,
        sources=[{"url": target["asset"], "type": "existing_publication"}
                 for target in targets],
        sensitive_actions=["medical_content"],
        risk={"level": "medium", "score": 5, "notes": [
            "Search Console evidence selected intent winners before URL changes.",
            "Duplicate losers are not unpublished because redirects are unavailable.",
            "The article body is unchanged.",
        ]},
        compliance={
            "exact_existing_post_required": True,
            "abort_on_slug_collision": True,
            "article_body_change_prohibited": True,
            "redirect_verification_required": True,
            "duplicate_loser_change_prohibited": True,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "approval_bundles")
    args = parser.parse_args()
    bundle = build_primary_bundle()
    args.output_root.mkdir(parents=True, exist_ok=True)
    bundle_path = args.output_root / f"{bundle['approval_id']}.json"
    preview_path = args.output_root / f"{bundle['approval_id']}.html"
    bundle_path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    preview_path.write_text(render_preview(bundle), encoding="utf-8")
    print(json.dumps({
        "approval_id": bundle["approval_id"],
        "bundle_path": str(bundle_path),
        "preview_path": str(preview_path),
        "targets": len(bundle["targets"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
