#!/usr/bin/env python3
"""Prepare P4 opportunity work orders without executing public actions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from reputation_core import CommandCenter, data_path
    from reputation_core.installation import installation_root
except ModuleNotFoundError:  # Imported as scripts.prepare_opportunities in tests.
    from scripts.reputation_core import CommandCenter, data_path
    from scripts.reputation_core.installation import installation_root


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _markdown(opportunity: dict, prepared_at: str) -> str:
    actions = opportunity.get("recommended_actions") or []
    requirements = opportunity.get("approval_bundle_requirements") or []
    evidence = json.dumps(
        opportunity.get("evidence") or {},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return "\n".join([
        f"# P4 action work order: {opportunity['id']}",
        "",
        f"- Prepared: {prepared_at}",
        f"- Action type: `{opportunity['action_type']}`",
        f"- Opportunity score: {opportunity['score']}",
        f"- Query: {opportunity.get('query') or 'not query-specific'}",
        f"- Asset: {opportunity.get('asset_url') or opportunity.get('asset_id') or 'external/new'}",
        f"- Required approver: {opportunity.get('approval_required')}",
        "- Public execution: blocked until item approval",
        "",
        "## Why now",
        "",
        opportunity.get("reason") or "Evidence-led opportunity selected by P4.",
        "",
        "## Prepared action sequence",
        "",
        *([f"{index}. {action}" for index, action in enumerate(actions, 1)]
          or ["1. Complete the exact proposed change before requesting approval."]),
        "",
        "## Approval bundle checklist",
        "",
        *([f"- [ ] {item}" for item in requirements]
          or ["- [ ] Exact proposed action and rollback condition"]),
        "",
        "## Evidence",
        "",
        "```json",
        evidence,
        "```",
        "",
        "## Decision",
        "",
        "- [ ] Approve this exact item",
        "- [ ] Reject",
        "- [ ] Return for revision",
        "",
        "Any edit after approval requires a new item approval.",
        "",
    ])


def prepare_selected_opportunities(
    command_center_path: str | Path,
    output_dir: str | Path,
) -> dict:
    """Create immutable review bundles for selected P4 opportunities."""
    center = CommandCenter(str(command_center_path))
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    prepared = []
    skipped = []
    for item in center.state.get("opportunities", []):
        if item.get("status") != "selected_for_preparation":
            continue
        if item.get("blocked_reasons"):
            item["status"] = "blocked"
            skipped.append({"id": item["id"], "reason": "blocked"})
            continue
        prepared_at = _now()
        json_path = output / f"{item['id']}.json"
        markdown_path = output / f"{item['id']}.md"
        if not json_path.exists():
            bundle = {
                "version": 4,
                "opportunity_id": item["id"],
                "prepared_at": prepared_at,
                "status": "awaiting_item_approval",
                "public_execution_allowed": False,
                "approval_invalidated_by_any_edit": True,
                "opportunity": item,
            }
            json_path.write_text(
                json.dumps(bundle, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            markdown_path.write_text(
                _markdown(item, prepared_at),
                encoding="utf-8",
            )
            prepared.append(item["id"])
        else:
            skipped.append({"id": item["id"], "reason": "already_prepared"})
        item["status"] = "prepared_awaiting_approval"
        try:
            artifact = json_path.relative_to(installation_root())
        except ValueError:
            artifact = json_path
        item["prepared_artifact"] = str(artifact)
        item["public_execution_allowed"] = False
    center._audit(
        "p4_opportunities_prepared",
        "opportunity_portfolio",
        {"prepared": prepared, "skipped": skipped},
    )
    center.save()
    return {"prepared": prepared, "skipped": skipped}


def main() -> None:
    result = prepare_selected_opportunities(
        data_path("command_center.json"),
        installation_root() / "opportunity_drafts",
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
