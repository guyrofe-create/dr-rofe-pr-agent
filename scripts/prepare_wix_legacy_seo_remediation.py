#!/usr/bin/env python3
"""Prepare an exact P7 bundle for legacy Wix SEO corrections."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from campaign_run import public_slug
from daily_run import load_draft
from reputation_core.approval_workflow import build_bundle, render_preview
from reputation_core.entity_contract import meta_description
from reputation_core.publication_seo import unbranded_title
from reputation_core.strategy import load_client_profile


def build_wix_bundle() -> dict:
    profile = load_client_profile()
    campaigns = json.loads(
        (ROOT / "content_drafts" / "campaigns" / "index.json").read_text(
            encoding="utf-8"
        )
    ).get("campaigns", [])
    targets = []
    for campaign in campaigns:
        for destination in campaign.get("destinations", []):
            old_url = destination.get("url") or ""
            parsed = urlparse(old_url)
            if (
                destination.get("status") != "published"
                or parsed.netloc.lower().removeprefix("www.") != "drguyrofe.com"
                or "pilot" not in parsed.path
            ):
                continue
            draft_title, content = load_draft(ROOT / campaign["draft"])
            new_title = unbranded_title(draft_title)
            new_slug = public_slug(new_title)[:100].rstrip("-")
            new_url = f"https://www.drguyrofe.com/post/{new_slug}"
            targets.append({
                "target_id": "legacy_wix_" + hashlib.sha256(
                    old_url.encode("utf-8")
                ).hexdigest()[:16],
                "platform": "Wix SEO remediation",
                "asset": old_url,
                "payload": {
                    "site_key": "DRGUYROFE_COM",
                    "old_url": old_url,
                    "old_slug": parsed.path.rstrip("/").split("/")[-1],
                    "expected_current_title": draft_title,
                    "new_title": new_title,
                    "new_slug": new_slug,
                    "expected_new_url": new_url,
                    "meta_description": meta_description(content, profile),
                    "changes": [
                        "remove_duplicate_brand_suffix_from_cms_title",
                        "replace_internal_pilot_slug_with_readable_topic_slug",
                        "replace_excerpt_with_complete_description",
                    ],
                },
            })
    return build_bundle(
        action_type="legacy_wix_seo_remediation",
        objective="Correct exact legacy Wix titles, URLs and descriptions.",
        query="ד״ר גיא רופא",
        targets=targets,
        sources=[{"url": target["asset"], "type": "existing_publication"}
                 for target in targets],
        sensitive_actions=["medical_content"],
        risk={"level": "medium", "score": 5, "notes": [
            "Every target is an exact existing Wix post.",
            "The provider update is followed by publication and redirect verification.",
        ]},
        compliance={
            "exact_existing_post_required": True,
            "abort_on_slug_collision": True,
            "article_body_change_prohibited": True,
            "redirect_verification_required": True,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "approval_bundles")
    args = parser.parse_args()
    bundle = build_wix_bundle()
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
