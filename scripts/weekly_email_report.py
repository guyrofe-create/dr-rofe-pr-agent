#!/usr/bin/env python3
"""Build and email the weekly product activity, publication and AI-cost report."""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import smtplib
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TO = "guyrofe@gmail.com"
CAMPAIGN_INDEX = ROOT / "content_drafts" / "campaigns" / "index.json"
DRAFT_INDEX = ROOT / "content_drafts" / "index.json"
BUNDLE_INDEX = ROOT / "approval_bundles" / "index.json"
HISTORY_PATH = ROOT / "data" / "reputation_history.json"


def _load_usage_reader():
    """Load the standalone ledger without importing optional monitor dependencies."""
    module_path = ROOT / "scripts" / "reputation_core" / "ai_usage.py"
    spec = importlib.util.spec_from_file_location(
        "weekly_report_ai_usage",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load AI usage ledger: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_usage_events


load_usage_events = _load_usage_reader()


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def in_window(value, start, end):
    parsed = parse_time(value)
    return bool(parsed and start <= parsed < end)


def latest_asset_rank_measurement(root):
    history = load_json(Path(root) / "data" / "reputation_history.json", {"snapshots": []})
    for snapshot in reversed(history.get("snapshots", [])):
        measurement = (
            (snapshot.get("orchestration") or {})
            .get("visibility_measurement", {})
            .get("asset_rank_changes", {})
        )
        if measurement.get("assets"):
            return measurement
    return {"status": "not_measured", "assets": []}


def collect_report(start, end, *, root=ROOT, usage_dir=None):
    root = Path(root)
    campaigns = load_json(
        root / "content_drafts" / "campaigns" / "index.json",
        {"campaigns": []},
    ).get("campaigns", [])
    drafts = load_json(
        root / "content_drafts" / "index.json",
        {"drafts": []},
    ).get("drafts", [])
    bundles = load_json(
        root / "approval_bundles" / "index.json",
        {"bundles": []},
    ).get("bundles", [])
    usage = load_usage_events(
        start,
        end,
        usage_dir=usage_dir or root / "data" / "ai_usage_events",
    )
    weekly_campaigns = [
        item
        for item in campaigns
        if in_window(item.get("published_at"), start, end)
    ]
    publications = []
    failures = []
    for campaign in weekly_campaigns:
        for destination in campaign.get("destinations", []):
            row = {
                "campaign_title": campaign.get("title") or "ללא כותרת",
                "name": destination.get("name") or "יעד לא ידוע",
                "status": destination.get("status") or "unknown",
                "url": destination.get("url"),
                "detail": destination.get("detail"),
            }
            if row["status"] == "published" and row["url"]:
                publications.append(row)
            elif row["status"] in {
                "failed", "blocked", "reconciliation_required",
            }:
                failures.append(row)

    operation_counts = Counter(item.get("operation", "unknown") for item in usage)
    model_counts = Counter(item.get("model", "unknown") for item in usage)
    known_cost = sum(
        float(item["estimated_cost_usd"])
        for item in usage
        if item.get("estimated_cost_usd") is not None
    )
    unknown_cost_events = sum(
        1 for item in usage if item.get("estimated_cost_usd") is None
    )
    return {
        "start": start,
        "end": end,
        "drafts": [
            item
            for item in drafts
            if in_window(item.get("generated_at"), start, end)
        ],
        "bundles": [
            item
            for item in bundles
            if in_window(item.get("created_at"), start, end)
        ],
        "campaigns": weekly_campaigns,
        "publications": publications,
        "failures": failures,
        "asset_rank": latest_asset_rank_measurement(root),
        "ai": {
            "events": len(usage),
            "input_tokens": sum(item.get("input_tokens", 0) for item in usage),
            "cached_input_tokens": sum(
                item.get("cached_input_tokens", 0) for item in usage
            ),
            "cache_write_tokens": sum(
                item.get("cache_write_tokens", 0) for item in usage
            ),
            "output_tokens": sum(item.get("output_tokens", 0) for item in usage),
            "web_search_calls": sum(
                item.get("web_search_calls", 0) for item in usage
            ),
            "estimated_cost_usd": round(known_cost, 4),
            "unknown_cost_events": unknown_cost_events,
            "operations": dict(operation_counts),
            "models": dict(model_counts),
        },
    }


def _number(value):
    return f"{int(value):,}"


def _rank_position_label(item):
    position = item.get("current_position")
    if position:
        return str(position)
    depth = item.get("current_result_depth")
    return f"מעל {depth}" if depth else "לא נמדד"


def _previous_rank_position_label(item):
    position = item.get("previous_position")
    if position:
        return str(position)
    depth = item.get("previous_result_depth")
    return f"מעל {depth}" if depth else "מדידת בסיס"


def _rank_page_label(item):
    page = item.get("current_result_page")
    if page:
        return str(page)
    depth = item.get("current_result_depth")
    return f"מעל {max(1, (int(depth) + 9) // 10)}" if depth else "לא נמדד"


def _rank_change_label(item):
    labels = {
        "baseline": "מדידת בסיס",
        "improved": "עלה",
        "declined": "ירד",
        "unchanged": "ללא שינוי",
        "entered_measured_results": "נכנס לטווח המדידה",
        "left_measured_results": "יצא מטווח המדידה",
        "unchanged_not_found": "עדיין מעבר לטווח המדידה",
    }
    label = labels.get(item.get("change"), item.get("change") or "לא ידוע")
    delta = item.get("delta")
    if delta:
        return f"{label} {abs(int(delta))} מקומות"
    return label


def render_html(report):
    start = report["start"].date().isoformat()
    end = (report["end"] - timedelta(seconds=1)).date().isoformat()
    ai = report["ai"]
    publication_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['campaign_title'])}</td>"
        f"<td>{html.escape(item['name'])}</td>"
        f"<td><a href=\"{html.escape(item['url'], quote=True)}\">פתיחת הפרסום</a></td>"
        "</tr>"
        for item in report["publications"]
    ) or '<tr><td colspan="3">לא נרשמו פרסומים מאומתים השבוע.</td></tr>'
    failure_rows = "".join(
        "<li>"
        f"{html.escape(item['campaign_title'])} — "
        f"{html.escape(item['name'])}: {html.escape(item.get('detail') or item['status'])}"
        "</li>"
        for item in report["failures"]
    ) or "<li>לא נרשמו כשלים המחייבים טיפול.</li>"
    operations = "".join(
        f"<li>{html.escape(name)}: {_number(count)}</li>"
        for name, count in sorted(ai["operations"].items())
    ) or "<li>לא נרשמו קריאות AI בתקופה.</li>"
    draft_items = "".join(
        f"<li>{html.escape(item.get('title') or item.get('path') or 'טיוטה')}</li>"
        for item in report["drafts"]
    ) or "<li>לא נוצרו טיוטות השבוע.</li>"
    bundle_items = "".join(
        f"<li>{html.escape(item.get('approval_id') or 'חבילת אישור')}</li>"
        for item in report["bundles"]
    ) or "<li>לא הוכנו חבילות אישור השבוע.</li>"
    rank = report.get("asset_rank", {})
    rank_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.get('platform') or item.get('asset_id') or 'נכס')}</td>"
        f"<td><a href=\"{html.escape(item.get('url') or '', quote=True)}\">{html.escape(item.get('url') or '')}</a></td>"
        f"<td>{html.escape(_rank_page_label(item))}</td>"
        f"<td>{html.escape(_previous_rank_position_label(item))}</td>"
        f"<td>{html.escape(_rank_position_label(item))}</td>"
        f"<td>{html.escape(_rank_change_label(item))}</td>"
        "</tr>"
        for item in rank.get("assets", [])
    ) or '<tr><td colspan="6">אין מדידת Google מלאה ועדכנית.</td></tr>'
    coverage_note = (
        "<p><strong>הערת כיסוי:</strong> העלות מבוססת על אירועי שימוש "
        "שנרשמו בפועל. קריאות שקדמו להפעלת המונה אינן נכללות.</p>"
    )
    if ai["unknown_cost_events"]:
        coverage_note += (
            "<p>בחלק מהקריאות לא נמצאה טבלת מחיר מוכרת; הטוקנים נכללו "
            "אך העלות שלהן לא נכללה בסכום.</p>"
        )
    return f"""<!doctype html>
<html lang="he" dir="rtl">
<head><meta charset="utf-8"><title>דוח שבועי</title></head>
<body style="font-family:Arial,sans-serif;direction:rtl;color:#172033;line-height:1.55">
<h1>דוח שבועי — מוצר ניהול המוניטין של ד״ר גיא רופא</h1>
<p>{start} עד {end}</p>
<h2>תקציר</h2>
<ul>
  <li>טיוטות שנוצרו: {len(report['drafts'])}</li>
  <li>חבילות אישור שהוכנו: {len(report['bundles'])}</li>
  <li>קמפיינים שנשלחו להפצה: {len(report['campaigns'])}</li>
  <li>פרסומים מאומתים עם קישור: {len(report['publications'])}</li>
  <li>כשלים המחייבים תשומת לב: {len(report['failures'])}</li>
</ul>
<h2>עלות ושימוש ב‑AI</h2>
<ul>
  <li>עלות API מחושבת: <strong>${ai['estimated_cost_usd']:.4f}</strong></li>
  <li>טוקני קלט: {_number(ai['input_tokens'])}</li>
  <li>מתוכם קלט שמור: {_number(ai['cached_input_tokens'])}</li>
  <li>טוקנים שנכתבו למטמון: {_number(ai['cache_write_tokens'])}</li>
  <li>טוקני פלט, כולל reasoning מחויב: {_number(ai['output_tokens'])}</li>
  <li>פעולות חיפוש רשת של OpenAI: {_number(ai['web_search_calls'])}</li>
</ul>
{coverage_note}
<h3>קריאות לפי פעולה</h3><ul>{operations}</ul>
<h2>פעולות שבוצעו</h2>
<h3>טיוטות שנוצרו</h3><ul>{draft_items}</ul>
<h3>חבילות אישור שהוכנו</h3><ul>{bundle_items}</ul>
<h2>פרסומים וקישורים</h2>
<table style="border-collapse:collapse;width:100%" border="1" cellpadding="7">
<thead><tr><th>תוכן</th><th>יעד</th><th>קישור</th></tr></thead>
<tbody>{publication_rows}</tbody>
</table>
<h2>כשלים או חסימות</h2><ul>{failure_rows}</ul>
<h2>מיקום כל נכס ב-Google</h2>
<p>מועד מדידה: {html.escape(rank.get('current_observed_at') or 'לא נמדד')}</p>
<table style="border-collapse:collapse;width:100%" border="1" cellpadding="7">
<thead><tr><th>נכס</th><th>כתובת</th><th>עמוד</th><th>מיקום קודם</th><th>מיקום נוכחי</th><th>שינוי</th></tr></thead>
<tbody>{rank_rows}</tbody>
</table>
<p style="color:#667085">הדוח כולל רק פרסום שקיבל קבלה וקישור במערכת.</p>
</body></html>"""


def render_text(report):
    ai = report["ai"]
    lines = [
        "דוח שבועי — מוצר ניהול המוניטין של ד״ר גיא רופא",
        f"{report['start'].date()} עד {(report['end'] - timedelta(seconds=1)).date()}",
        "",
        f"טיוטות: {len(report['drafts'])}",
        f"חבילות אישור: {len(report['bundles'])}",
        f"קמפיינים: {len(report['campaigns'])}",
        f"פרסומים מאומתים: {len(report['publications'])}",
        f"עלות API מחושבת: ${ai['estimated_cost_usd']:.4f}",
        f"טוקני קלט: {_number(ai['input_tokens'])}",
        f"טוקני פלט: {_number(ai['output_tokens'])}",
        f"חיפושי OpenAI: {_number(ai['web_search_calls'])}",
        "",
        "פרסומים:",
    ]
    lines.extend(
        f"- {item['campaign_title']} — {item['name']}: {item['url']}"
        for item in report["publications"]
    )
    if not report["publications"]:
        lines.append("- לא נרשמו פרסומים מאומתים השבוע.")
    lines.append("")
    lines.append("כשלים:")
    lines.extend(
        f"- {item['campaign_title']} — {item['name']}: "
        f"{item.get('detail') or item['status']}"
        for item in report["failures"]
    )
    if not report["failures"]:
        lines.append("- לא נרשמו כשלים המחייבים טיפול.")
    lines.extend(["", "מיקום כל נכס ב-Google:"])
    rank = report.get("asset_rank", {})
    lines.append(f"מועד מדידה: {rank.get('current_observed_at') or 'לא נמדד'}")
    for item in rank.get("assets", []):
        lines.append(
            f"- {item.get('platform') or item.get('asset_id')}: "
            f"עמוד {_rank_page_label(item)}, "
            f"מיקום קודם {_previous_rank_position_label(item)}, "
            f"מיקום נוכחי {_rank_position_label(item)}, "
            f"שינוי {_rank_change_label(item)} — {item.get('url') or ''}"
        )
    if not rank.get("assets"):
        lines.append("- אין מדידת Google מלאה ועדכנית.")
    return "\n".join(lines) + "\n"


def send_email(report, *, recipient, username, app_password):
    message = EmailMessage()
    end_date = (report["end"] - timedelta(seconds=1)).date()
    message["Subject"] = f"דוח שבועי מוצר המוניטין — {end_date}"
    message["From"] = username
    message["To"] = recipient
    message.set_content(render_text(report))
    message.add_alternative(render_html(report), subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, app_password)
        smtp.send_message(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end", help="UTC ISO timestamp; defaults to now")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--html-output", type=Path)
    args = parser.parse_args()
    end = (
        parse_time(args.end)
        if args.end
        else datetime.now(timezone.utc)
    )
    if not end:
        raise SystemExit("--end must be a valid ISO timestamp")
    start = end - timedelta(days=args.days)
    report = collect_report(start, end)
    rendered = render_html(report)
    if args.html_output:
        args.html_output.parent.mkdir(parents=True, exist_ok=True)
        args.html_output.write_text(rendered, encoding="utf-8")
    if args.dry_run:
        print(render_text(report))
        return
    username = os.environ.get(
        "WEEKLY_REPORT_GMAIL_USERNAME",
        DEFAULT_TO,
    ).strip()
    recipient = os.environ.get(
        "WEEKLY_REPORT_TO",
        DEFAULT_TO,
    ).strip()
    app_password = os.environ.get(
        "WEEKLY_REPORT_GMAIL_APP_PASSWORD",
        "",
    ).replace(" ", "")
    if not app_password:
        raise SystemExit(
            "WEEKLY_REPORT_GMAIL_APP_PASSWORD is required for Gmail SMTP"
        )
    send_email(
        report,
        recipient=recipient,
        username=username,
        app_password=app_password,
    )
    print(f"Weekly report sent to {recipient}")


if __name__ == "__main__":
    main()
