#!/usr/bin/env python3
"""Open, review and explicitly activate one P2 reputation campaign."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reputation_core.campaign_wizard import (
    apply_approved_campaign,
    build_campaign_draft,
    parse_plain_language_brief,
)
from reputation_core.installation import installation_root


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def print_summary(draft: dict) -> None:
    print("Campaign draft ready; nothing was published.")
    print("Approval ID:", draft["approval_id"])
    print("Primary queries:", ", ".join(
        item["query"] for item in draft["queries"]["primary"]
    ))
    print("Secondary queries:", ", ".join(
        item["query"] for item in draft["queries"]["secondary"]
    ) or "(none)")
    print("Desired outcome:", draft["plain_language_goal"]["desired_outcome"])
    print("Assets:", ", ".join(
        asset["request"] for asset in draft["assets"]
    ))
    print("Prohibitions:", ", ".join(
        draft["content_constraints"]["customer_prohibitions"]
    ))


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--brief")
    mode.add_argument("--brief-file", type=Path)
    mode.add_argument("--intake-json", type=Path)
    mode.add_argument("--approve", metavar="APPROVAL_ID")
    parser.add_argument(
        "--draft-path",
        type=Path,
        help="Defaults to <installation>/data/campaign_draft.json",
    )
    args = parser.parse_args()
    root = installation_root()
    draft_path = args.draft_path or root / "data" / "campaign_draft.json"

    if args.approve:
        draft = load_json(draft_path)
        activated = apply_approved_campaign(root, draft, args.approve)
        print("Campaign activated:", activated["approval_id"])
        print("No public content was published.")
        return

    profile = load_json(root / "config" / "client_profile.json")
    facts = load_json(root / "data" / "fact_registry.json")
    assets = load_json(root / "data" / "asset_registry.json")
    if args.intake_json:
        intake = load_json(args.intake_json)
    else:
        brief = args.brief or args.brief_file.read_text(encoding="utf-8")
        intake = parse_plain_language_brief(brief)
    draft = build_campaign_draft(intake, profile, facts, assets)
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(
        json.dumps(draft, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print_summary(draft)
    print(f"Review file: {draft_path.resolve()}")
    print(
        "To activate this exact draft, run: "
        f"python scripts/open_campaign.py --approve {draft['approval_id']}"
    )


if __name__ == "__main__":
    main()
