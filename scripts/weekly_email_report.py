#!/usr/bin/env python3
"""Build and email the weekly product activity, publication and AI-cost report."""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import smtplib
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse

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


def _normalized_host(value):
    try:
        return urlparse(value or "").netloc.lower().removeprefix("www.")
    except (TypeError, ValueError):
        return ""


def _execution_matches_asset(execution, asset):
    publication_url = execution.get("url") or ""
    asset_url = asset.get("url") or ""
    publication_host = _normalized_host(publication_url)
    asset_host = _normalized_host(asset_url)
    if publication_host and publication_host == asset_host:
        asset_path = urlparse(asset_url).path.rstrip("/") or "/"
        publication_path = urlparse(publication_url).path.rstrip("/") or "/"
        if asset_path == "/" or publication_path == asset_path:
            return True
        if publication_path.startswith(asset_path + "/"):
            return True
    platform = str(execution.get("platform") or "").casefold()
    asset_platform = str(asset.get("platform") or "").casefold()
    return bool(platform and platform == asset_platform)


def _outcome_assessment(asset):
    publications = int(asset.get("publications_since_previous") or 0)
    change = asset.get("change")
    if not asset.get("previous_measurement_available"):
        return "baseline"
    if not publications:
        return "no_recent_publication"
    if change in {"improved", "entered_measured_results"}:
        return "improved_after_publication"
    if change in {"declined", "left_measured_results"}:
        return "declined_after_publication"
    if change == "unchanged_not_found":
        return "still_not_found_after_publication"
    return "no_improvement_after_publication"


def _utc_time(value):
    parsed = parse_time(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _annotate_publication_outcomes(measurement, root):
    previous = _utc_time(measurement.get("previous_observed_at"))
    current = _utc_time(measurement.get("current_observed_at"))
    ledger = load_json(
        Path(root) / "publication_receipts" / "execution_ledger.json",
        {"executions": {}},
    )
    published = [
        execution
        for execution in ledger.get("executions", {}).values()
        if execution.get("status") == "published" and execution.get("url")
    ]
    for asset in measurement.get("assets", []):
        matching = []
        if previous and current:
            for execution in published:
                observed = _utc_time(execution.get("published_at"))
                if (
                    observed
                    and previous < observed <= current
                    and _execution_matches_asset(execution, asset)
                ):
                    matching.append(execution)
        asset["previous_measurement_available"] = bool(previous)
        asset["publications_since_previous"] = len(matching)
        asset["latest_publication_at"] = max(
            (item.get("published_at") for item in matching),
            default=None,
        )
        asset["outcome_assessment"] = _outcome_assessment(asset)
    measurement["outcome_summary"] = {
        "tracked_assets": len(measurement.get("assets", [])),
        "found_assets": sum(
            item.get("current_position") is not None
            for item in measurement.get("assets", [])
        ),
        "improved_assets": sum(
            item.get("change") in {"improved", "entered_measured_results"}
            for item in measurement.get("assets", [])
        ),
        "declined_assets": sum(
            item.get("change") in {"declined", "left_measured_results"}
            for item in measurement.get("assets", [])
        ),
        "assets_published_between_measurements": sum(
            bool(item.get("publications_since_previous"))
            for item in measurement.get("assets", [])
        ),
        "publication_placements_between_measurements": sum(
            int(item.get("publications_since_previous") or 0)
            for item in measurement.get("assets", [])
        ),
    }
    return measurement


def latest_asset_rank_measurement(root):
    history = load_json(Path(root) / "data" / "reputation_history.json", {"snapshots": []})
    for snapshot in reversed(history.get("snapshots", [])):
        measurement = (
            (snapshot.get("orchestration") or {})
            .get("visibility_measurement", {})
            .get("asset_rank_changes", {})
        )
        if measurement.get("assets"):
            return _annotate_publication_outcomes(measurement, root)
    registry = load_json(
        Path(root) / "data" / "asset_registry.json",
        {"assets": []},
    )
    rows = []
    seen = set()
    for asset in registry.get("assets", []):
        if not asset.get("url"):
            continue
        key = (
            str(asset.get("platform") or "").casefold(),
            str(asset.get("url") or "").rstrip("/"),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "asset_id": asset.get("id") or asset.get("platform"),
            "platform": asset.get("platform"),
            "url": asset.get("url"),
            "tier": asset.get("tier"),
            "asset_status": asset.get("status"),
            "optimization_allowed": asset.get("status") != "quarantined",
            "previous_position": None,
            "current_position": None,
            "previous_result_depth": None,
            "current_result_depth": None,
            "previous_result_page": None,
            "current_result_page": None,
            "previous_query": None,
            "current_query": None,
            "change": "baseline",
            "changed": None,
            "delta": None,
        })
    return _annotate_publication_outcomes({
        "status": "not_measured",
        "reason": "awaiting the first complete Google baseline measurement",
        "current_observed_at": None,
        "previous_observed_at": None,
        "asset_count": len(rows),
        "assets": rows,
    }, root)


def _aggregate_search_console_pages(rows):
    pages = {}
    for row in rows or []:
        page = row.get("page")
        if not page:
            continue
        item = pages.setdefault(page, {
            "page": page,
            "property": row.get("property"),
            "clicks": 0.0,
            "impressions": 0.0,
            "position_weight": 0.0,
            "position_samples": [],
            "queries": [],
        })
        clicks = float(row.get("clicks") or 0)
        impressions = float(row.get("impressions") or 0)
        position = float(row.get("position") or 0)
        item["clicks"] += clicks
        item["impressions"] += impressions
        item["position_weight"] += position * max(impressions, 1)
        item["position_samples"].append((position, max(impressions, 1)))
        item["queries"].append({
            "query": row.get("query") or "",
            "clicks": clicks,
            "impressions": impressions,
            "ctr": float(row.get("ctr") or 0),
            "position": position,
        })
    for item in pages.values():
        denominator = sum(weight for _, weight in item.pop("position_samples"))
        item["position"] = (
            item.pop("position_weight") / denominator if denominator else None
        )
        item["ctr"] = (
            item["clicks"] / item["impressions"]
            if item["impressions"]
            else 0.0
        )
        item["queries"].sort(
            key=lambda query: (-query["impressions"], -query["clicks"], query["query"])
        )
        item["queries"] = item["queries"][:3]
    return pages


def latest_search_console_performance(root):
    """Return article-level query, click, CTR and position comparisons."""
    history = load_json(Path(root) / "data" / "reputation_history.json", {"snapshots": []})
    measurements_by_period = {}
    for snapshot in history.get("snapshots", []):
        measurement = snapshot.get("search_console") or {}
        rows = measurement.get("rows") or []
        if measurement.get("status") != "ok" or not rows:
            continue
        period = rows[0].get("period") or {}
        key = (period.get("start"), period.get("end"))
        measurements_by_period[key] = measurement
    measurements = list(measurements_by_period.values())
    if not measurements:
        return {"status": "not_measured", "pages": [], "page_count": 0}
    current = measurements[-1]
    previous = measurements[-2] if len(measurements) > 1 else {"rows": []}
    current_pages = _aggregate_search_console_pages(current.get("rows"))
    previous_pages = _aggregate_search_console_pages(previous.get("rows"))
    pages = []
    for page in sorted(set(current_pages) | set(previous_pages)):
        now = current_pages.get(page, {"page": page, "clicks": 0, "impressions": 0,
                                       "ctr": 0, "position": None, "queries": []})
        before = previous_pages.get(page, {})
        row = dict(now)
        row.update({
            "previous_clicks": before.get("clicks", 0),
            "previous_impressions": before.get("impressions", 0),
            "previous_ctr": before.get("ctr", 0),
            "previous_position": before.get("position"),
            "click_change": now.get("clicks", 0) - before.get("clicks", 0),
            "impression_change": (
                now.get("impressions", 0) - before.get("impressions", 0)
            ),
            "position_change": (
                before.get("position") - now.get("position")
                if before.get("position") is not None
                and now.get("position") is not None
                else None
            ),
        })
        pages.append(row)
    pages.sort(key=lambda item: (-item["impressions"], -item["clicks"], item["page"]))
    issues = []
    for item in pages:
        if re.search(r"(?:pilot|run-\d+|attempt-\d+)", item["page"], re.I):
            issues.append({
                "kind": "internal_slug",
                "page": item["page"],
                "detail": "כתובת פנימית נחשפה בפרסום; נדרש מיפוי 301 מדויק",
            })
        if item["page"].startswith("http://"):
            issues.append({
                "kind": "legacy_http",
                "page": item["page"],
                "detail": "גרסת HTTP עדיין מקבלת חשיפות; יש לאחד הפניה וקנוניקל",
            })
        if (
            item["impressions"] >= 20
            and item.get("position") is not None
            and item["position"] <= 20
            and item["ctr"] < 0.03
        ):
            issues.append({
                "kind": "low_ctr",
                "page": item["page"],
                "detail": (
                    f"CTR {item['ctr'] * 100:.1f}% במיקום {item['position']:.1f}; "
                    "נדרש ניסוי כותרת ותיאור"
                ),
            })
        if item.get("position_change") is not None and item["position_change"] <= -3:
            issues.append({
                "kind": "position_decline",
                "page": item["page"],
                "detail": f"ירידה של {abs(item['position_change']):.1f} מקומות",
            })
    query_pages = {}
    for row in current.get("rows") or []:
        impressions = float(row.get("impressions") or 0)
        if impressions < 3 or not row.get("query") or not row.get("page"):
            continue
        pages_for_query = query_pages.setdefault(row["query"], {})
        pages_for_query[row["page"]] = (
            pages_for_query.get(row["page"], 0) + impressions
        )
    for query, matching_pages in query_pages.items():
        if len(matching_pages) > 1 and sum(matching_pages.values()) >= 20:
            issues.append({
                "kind": "query_cannibalization",
                "query": query,
                "pages": sorted(matching_pages),
                "detail": f"אותה שאילתה מופיעה עבור {len(matching_pages)} עמודים",
            })
    current_period = (current.get("rows") or [{}])[0].get("period") or {}
    previous_period = (previous.get("rows") or [{}])[0].get("period") or {}
    return {
        "status": "compared" if previous.get("rows") else "baseline",
        "period": current_period,
        "previous_period": previous_period,
        "row_count": len(current.get("rows") or []),
        "page_count": len(pages),
        "pages": pages,
        "issues": issues,
    }


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
                "primary_query": (
                    campaign.get("search_target") or {}
                ).get("primary_query"),
                "name": destination.get("name") or "יעד לא ידוע",
                "status": destination.get("status") or "unknown",
                "url": destination.get("url"),
                "detail": destination.get("detail"),
            }
            if row["status"] == "published" and row["url"]:
                publications.append(row)
            elif row["status"] in {
                "failed", "blocked", "reconciliation_required", "seo_warning",
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
        "search_console": latest_search_console_performance(root),
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


def _signed_number(value):
    value = float(value or 0)
    return f"{value:+.0f}"


def _position(value):
    return "לא נמדד" if value is None else f"{float(value):.1f}"


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


def _rank_outcome_label(item):
    labels = {
        "baseline": "מדידת בסיס",
        "no_recent_publication": "לא היה פרסום בנכס בין המדידות",
        "improved_after_publication": "נמדד שיפור לאחר פרסום (לא הוכחת סיבתיות)",
        "declined_after_publication": "נמדדה ירידה לאחר פרסום",
        "still_not_found_after_publication": "פורסם, אך עדיין מעבר לטווח המדידה",
        "no_improvement_after_publication": "פורסם, אך טרם נמדד שיפור",
    }
    return labels.get(
        item.get("outcome_assessment"),
        item.get("outcome_assessment") or "לא ידוע",
    )


def render_html(report):
    start = report["start"].date().isoformat()
    end = (report["end"] - timedelta(seconds=1)).date().isoformat()
    ai = report["ai"]
    publication_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item['campaign_title'])}</td>"
        f"<td>{html.escape(item.get('primary_query') or 'לא הוגדרה')}</td>"
        f"<td>{html.escape(item['name'])}</td>"
        f"<td><a href=\"{html.escape(item['url'], quote=True)}\">פתיחת הפרסום</a></td>"
        "</tr>"
        for item in report["publications"]
    ) or '<tr><td colspan="4">לא נרשמו פרסומים מאומתים השבוע.</td></tr>'
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
    outcome_summary = rank.get("outcome_summary", {})
    rank_rows = "".join(
        "<tr>"
        f"<td>{html.escape(item.get('platform') or item.get('asset_id') or 'נכס')}</td>"
        f"<td><a href=\"{html.escape(item.get('url') or '', quote=True)}\">{html.escape(item.get('url') or '')}</a></td>"
        f"<td>{html.escape(item.get('current_query') or 'לא נמדד')}</td>"
        f"<td>{html.escape(_rank_page_label(item))}</td>"
        f"<td>{html.escape(_previous_rank_position_label(item))}</td>"
        f"<td>{html.escape(_rank_position_label(item))}</td>"
        f"<td>{html.escape(_rank_change_label(item))}</td>"
        f"<td>{int(item.get('publications_since_previous') or 0)}</td>"
        f"<td>{html.escape(_rank_outcome_label(item))}</td>"
        "</tr>"
        for item in rank.get("assets", [])
    ) or '<tr><td colspan="9">אין מדידת Google מלאה ועדכנית.</td></tr>'
    search_console = report.get("search_console", {})
    search_console_rows = "".join(
        "<tr>"
        f'<td><a href="{html.escape(item["page"], quote=True)}">'
        f'{html.escape(item["page"])}</a></td>'
        f"<td>{html.escape('; '.join(query['query'] for query in item.get('queries', [])) or 'אין שאילתה')}</td>"
        f"<td>{_number(item.get('clicks', 0))} ({_signed_number(item.get('click_change'))})</td>"
        f"<td>{_number(item.get('impressions', 0))} ({_signed_number(item.get('impression_change'))})</td>"
        f"<td>{float(item.get('ctr') or 0) * 100:.1f}%</td>"
        f"<td>{_position(item.get('previous_position'))}</td>"
        f"<td>{_position(item.get('position'))}</td>"
        f"<td>{_signed_number(item.get('position_change'))}</td>"
        "</tr>"
        for item in search_console.get("pages", [])
    ) or '<tr><td colspan="8">אין כרגע מדידת Search Console זמינה.</td></tr>'
    seo_issue_items = "".join(
        "<li>"
        f"{html.escape(item.get('kind') or 'issue')}: "
        f"{html.escape(item.get('detail') or '')} "
        f"{html.escape(item.get('page') or item.get('query') or '')}"
        "</li>"
        for item in search_console.get("issues", [])
    ) or "<li>לא זוהו חריגות SEO לפי המדידה האחרונה.</li>"
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
<thead><tr><th>תוכן</th><th>שאילתת יעד</th><th>יעד</th><th>קישור</th></tr></thead>
<tbody>{publication_rows}</tbody>
</table>
<h2>כשלים או חסימות</h2><ul>{failure_rows}</ul>
<h2>מיקום כל נכס ב-Google</h2>
<p>מועד מדידה: {html.escape(rank.get('current_observed_at') or 'לא נמדד')}</p>
<p>נכסים במעקב: {int(outcome_summary.get('tracked_assets') or 0)};
נמצאו בטווח: {int(outcome_summary.get('found_assets') or 0)};
השתפרו: {int(outcome_summary.get('improved_assets') or 0)};
ירדו: {int(outcome_summary.get('declined_assets') or 0)}.</p>
<table style="border-collapse:collapse;width:100%" border="1" cellpadding="7">
<thead><tr><th>נכס</th><th>כתובת</th><th>שאילתת Google</th><th>עמוד</th><th>מיקום קודם</th><th>מיקום נוכחי</th><th>שינוי</th><th>פרסומים בין המדידות</th><th>הערכת תוצאה</th></tr></thead>
<tbody>{rank_rows}</tbody>
</table>
<h2>ביצועי כל עמוד ב-Google Search Console</h2>
<p>תקופה נוכחית: {html.escape(str(search_console.get('period') or 'לא נמדד'))};
עמודים בדוח: {int(search_console.get('page_count') or 0)}. שינוי חיובי במיקום פירושו עלייה.</p>
<table style="border-collapse:collapse;width:100%" border="1" cellpadding="7">
<thead><tr><th>עמוד</th><th>שאילתות מובילות</th><th>הקלקות ושינוי</th><th>חשיפות ושינוי</th><th>CTR</th><th>מיקום קודם</th><th>מיקום נוכחי</th><th>שינוי במיקום</th></tr></thead>
<tbody>{search_console_rows}</tbody>
</table>
<h3>חריגות הדורשות טיפול</h3><ul>{seo_issue_items}</ul>
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
        f"- {item['campaign_title']} — שאילתת יעד "
        f"{item.get('primary_query') or 'לא הוגדרה'} — "
        f"{item['name']}: {item['url']}"
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
    summary = rank.get("outcome_summary", {})
    if summary:
        lines.append(
            f"נכסים במעקב: {summary.get('tracked_assets', 0)}; "
            f"נמצאו בטווח: {summary.get('found_assets', 0)}; "
            f"השתפרו: {summary.get('improved_assets', 0)}; "
            f"ירדו: {summary.get('declined_assets', 0)}"
        )
    for item in rank.get("assets", []):
        lines.append(
            f"- {item.get('platform') or item.get('asset_id')}: "
            f"שאילתה {item.get('current_query') or 'לא נמדד'}, "
            f"עמוד {_rank_page_label(item)}, "
            f"מיקום קודם {_previous_rank_position_label(item)}, "
            f"מיקום נוכחי {_rank_position_label(item)}, "
            f"שינוי {_rank_change_label(item)}, "
            f"פרסומים בין המדידות {int(item.get('publications_since_previous') or 0)}, "
            f"הערכת תוצאה {_rank_outcome_label(item)} — {item.get('url') or ''}"
        )
    if not rank.get("assets"):
        lines.append("- אין מדידת Google מלאה ועדכנית.")
    search_console = report.get("search_console", {})
    lines.extend([
        "",
        "ביצועי כל עמוד ב-Google Search Console:",
        f"תקופה: {search_console.get('period') or 'לא נמדד'}; "
        f"עמודים: {int(search_console.get('page_count') or 0)}",
    ])
    for item in search_console.get("pages", []):
        queries = "; ".join(
            query.get("query") or "" for query in item.get("queries", [])
        ) or "אין שאילתה"
        lines.append(
            f"- {item['page']} — שאילתות: {queries}; "
            f"הקלקות {_number(item.get('clicks', 0))} "
            f"({_signed_number(item.get('click_change'))}); "
            f"חשיפות {_number(item.get('impressions', 0))} "
            f"({_signed_number(item.get('impression_change'))}); "
            f"CTR {float(item.get('ctr') or 0) * 100:.1f}%; "
            f"מיקום קודם {_position(item.get('previous_position'))}; "
            f"מיקום נוכחי {_position(item.get('position'))}; "
            f"שינוי {_signed_number(item.get('position_change'))}"
        )
    if not search_console.get("pages"):
        lines.append("- אין מדידת Search Console זמינה.")
    lines.append("")
    lines.append("חריגות SEO הדורשות טיפול:")
    for item in search_console.get("issues", []):
        lines.append(
            f"- {item.get('kind')}: {item.get('detail')} — "
            f"{item.get('page') or item.get('query') or ''}"
        )
    if not search_console.get("issues"):
        lines.append("- לא זוהו חריגות לפי המדידה האחרונה.")
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
