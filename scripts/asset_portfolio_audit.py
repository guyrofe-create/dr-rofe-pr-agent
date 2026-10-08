#!/usr/bin/env python3
"""Build a credential-free decision plan for every registered asset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.reputation_core.asset_portfolio import build_asset_portfolio_plan
except ModuleNotFoundError:
    from reputation_core.asset_portfolio import build_asset_portfolio_plan


ROOT = Path(__file__).resolve().parents[1]

EFFORT_HE = {
    "core": "ליבה — תחזוקה ומדידה שוטפות",
    "defend": "הגנה — כבר תופס נראות",
    "selective": "שימוש סלקטיבי",
    "resolve_or_hold": "תיקון לפני השקעה",
    "retain_only": "שמירה בלבד",
    "quarantine": "הסגר — ללא אוטומציה",
}
REACHABILITY_HE = {
    "reachable": "נגיש",
    "access_restricted_or_anti_bot": "חסימת בוט/בדיקה ידנית",
    "http_error": "שגיאת HTTP",
    "missing_url": "כתובת חסרה",
    "not_found": "לא נמצא",
    "network_or_provider_error": "שגיאת רשת/ספק",
    "not_checked": "לא נבדק",
}


def render_markdown(plan: dict) -> str:
    lines = [
        "# מפת נכסי המוניטין המלאה",
        "",
        f"נבדקו {plan['asset_count']} נכסים ייחודיים. הדוח אינו כולל פרטי התחברות ולא ביצע שינוי ציבורי.",
        "",
        "## חלוקת המאמץ",
        "",
    ]
    for key in ("core", "defend", "selective", "resolve_or_hold", "retain_only", "quarantine"):
        lines.append(f"- {EFFORT_HE[key]}: {plan['effort_counts'].get(key, 0)}")
    lines.extend([
        "",
        f"בדיקת תוכן/SEO מלאה ללא משימות פתוחות: {plan.get('audit_complete_count', 0)}; נכסים הדורשים פעולה או בדיקה ידנית: {plan.get('action_required_count', 0)}.",
        "",
        "## כל הנכסים",
        "",
        "| נכס | החלטת מאמץ | זמינות ציבורית | בדיקת תוכן | פעולות נדרשות | כתובת |",
        "|---|---|---|---|---|---|",
    ])
    for row in plan["assets"]:
        values = [
            row.get("platform") or "—",
            EFFORT_HE.get(row.get("effort"), row.get("effort") or "—"),
            REACHABILITY_HE.get(row.get("reachability"), row.get("reachability") or "—"),
            row.get("content_audit") or "—",
            ", ".join(row.get("action_checklist") or []) or "אין",
            row.get("url") or "—",
        ]
        values = [str(value).replace("|", "\\|").replace("\n", " ") for value in values]
        lines.append("| " + " | ".join(values) + " |")
    lines.extend([
        "",
        "הערה: חסימת בוט, 401/403/429 או שגיאת ספק אינן הוכחה שהנכס נעלם; הן מסמנות צורך בבדיקה ידנית. 404/410 מסומנים כתיקון לפני השקעה.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "data" / "asset_registry.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "asset_portfolio_plan.json")
    parser.add_argument("--reachability", type=Path, default=ROOT / "data" / "asset_reachability_audit.json")
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    reachability = (
        json.loads(args.reachability.read_text(encoding="utf-8"))
        if args.reachability.is_file() else None
    )
    plan = build_asset_portfolio_plan(registry, reachability=reachability)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(plan), encoding="utf-8")
    print(json.dumps({"assets": plan["asset_count"], "effort_counts": plan["effort_counts"],
                      "credentials_included": False, "public_execution_allowed": False}))


if __name__ == "__main__":
    main()
