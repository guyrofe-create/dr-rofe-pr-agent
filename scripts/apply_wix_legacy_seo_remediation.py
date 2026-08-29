#!/usr/bin/env python3
"""Apply one signed exact legacy Wix SEO remediation bundle."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import wix_blog
from campaign_run import load_business_profile, site_by_key
from reputation_core.approval_workflow import ExecutionLedger, verify_approval


def apply_target(target: dict) -> dict:
    payload = target["payload"]
    site = site_by_key(load_business_profile(), payload["site_key"])
    return wix_blog.update_published(
        site,
        old_slug=payload["old_slug"],
        expected_current_title=payload["expected_current_title"],
        title=payload["new_title"],
        excerpt=payload["meta_description"],
        slug=payload["new_slug"],
        old_url=payload["old_url"],
        expected_url=payload["expected_new_url"],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle_path", type=Path)
    parser.add_argument("approval_record_path", type=Path)
    parser.add_argument(
        "--ledger", type=Path,
        default=ROOT / "publication_receipts" / "seo_remediation_ledger.json",
    )
    args = parser.parse_args()
    bundle = json.loads(args.bundle_path.read_text(encoding="utf-8"))
    record = json.loads(args.approval_record_path.read_text(encoding="utf-8"))
    verify_approval(bundle, record, os.environ.get("APPROVAL_SIGNING_SECRET", ""))
    if bundle.get("action_type") != "legacy_wix_seo_remediation":
        raise PermissionError("Approval bundle is not a legacy Wix remediation")
    ledger = ExecutionLedger(args.ledger)
    results = []
    for target in bundle["targets"]:
        results.append(ledger.execute(
            bundle,
            target,
            lambda _payload, _key, exact_target=target: apply_target(exact_target),
        ))
    print(json.dumps({"updated": len(results), "results": results}, ensure_ascii=False))


if __name__ == "__main__":
    main()
