#!/usr/bin/env python3
"""Temporary, removable publication watchdog.

This module is deliberately isolated from the publisher. It reads immutable
campaign receipts, checks provider URLs, classifies failures, writes a JSON
report and optionally emails a daily Hebrew summary.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = PROJECT_ROOT / "content_drafts" / "campaigns"
SUCCESS_STATUSES = {"published", "skipped_duplicate"}
INCONCLUSIVE_HTTP = {401, 403, 429}


def parse_time(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def classify_failure(destination):
    name = destination.get("name", "Unknown")
    detail = str(destination.get("detail") or "")
    probe = detail.lower()
    if name == "Google Business Profile" and ("429" in probe or "quota" in probe):
        return {
            "category": "google_business_access_or_quota",
            "reason": "Google Business Profile API access/quota is unavailable (the project currently has a zero request quota).",
            "action": "Wait for Google's Basic API Access decision; do not submit a duplicate request before their review window ends.",
        }
    if name == "Instagram" and ("400" in probe or "media container" in probe):
        return {
            "category": "instagram_media_rejected",
            "reason": "Meta rejected the Instagram media container.",
            "action": "Use the approved JPEG square variant and retain Meta's structured error fields on the next attempt.",
        }
    if name == "Campaign" and detail.strip() in {"0", "KeyError: 0"}:
        return {
            "category": "legacy_untyped_exception",
            "reason": "The old receipt hid an exception as '0'; the likely failure occurred while reading the WordPress media lookup response.",
            "action": "The publisher now validates the WordPress JSON shape and records the exception class and provider message.",
        }
    if "reconcile" in probe or "may already be published" in probe:
        return {
            "category": "reconciliation_required",
            "reason": "The execution ledger cannot prove whether the provider accepted an earlier attempt.",
            "action": "Check the provider for the exact approved post and attach its URL to the receipt before any retry.",
        }
    return {
        "category": "provider_failure",
        "reason": detail or "The provider returned no usable detail.",
        "action": "Inspect the named provider response and retry only the exact approved destination after reconciliation.",
    }


def verify_url(url, name, *, request_get=requests.get):
    try:
        response = request_get(
            url,
            timeout=20,
            allow_redirects=True,
            headers={"User-Agent": "ReputationAgentWatchdog/1.0"},
        )
    except requests.RequestException as exc:
        return {"state": "unreachable", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    status = response.status_code
    if 200 <= status < 400:
        state = "verified_live"
    elif status in INCONCLUSIVE_HTTP and name in {"Facebook", "Instagram", "LinkedIn"}:
        state = "inconclusive_login_or_rate_limit"
    elif status in {404, 410}:
        state = "missing"
    else:
        state = "http_error"
    return {"state": state, "http_status": status, "final_url": response.url}


def load_recent_campaigns(hours, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)
    campaigns = []
    for path in sorted(CAMPAIGN_ROOT.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        published_at = parse_time(record.get("published_at"))
        if published_at and published_at >= cutoff:
            campaigns.append((path, record))
    return campaigns


def build_report(hours=30, *, now=None, request_get=requests.get):
    now = now or datetime.now(timezone.utc)
    campaign_reports = []
    totals = {"campaigns": 0, "published_receipts": 0, "verified_live": 0, "failures": 0, "missing_urls": 0}
    for path, campaign in load_recent_campaigns(hours, now=now):
        item = {
            "receipt": path.relative_to(PROJECT_ROOT).as_posix(),
            "title": campaign.get("title"),
            "status": campaign.get("status"),
            "published_at": campaign.get("published_at"),
            "approval_id": campaign.get("approval_id"),
            "destinations": [],
        }
        totals["campaigns"] += 1
        for destination in campaign.get("destinations", []):
            current = dict(destination)
            if current.get("status") in SUCCESS_STATUSES:
                totals["published_receipts"] += 1
                if current.get("url"):
                    current["verification"] = verify_url(
                        current["url"], current.get("name", ""), request_get=request_get
                    )
                    if current["verification"]["state"] == "verified_live":
                        totals["verified_live"] += 1
                    if current["verification"]["state"] == "missing":
                        totals["missing_urls"] += 1
                else:
                    current["verification"] = {"state": "receipt_missing_url"}
                    totals["missing_urls"] += 1
            elif current.get("status") == "failed":
                totals["failures"] += 1
                current["diagnosis"] = classify_failure(current)
            item["destinations"].append(current)
        campaign_reports.append(item)
    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "totals": totals,
        "campaigns": campaign_reports,
    }


def render_email(report):
    totals = report["totals"]
    lines = [
        f"דוח ניטור פרסומים יומי ({report['window_hours']} השעות האחרונות)",
        f"קמפיינים: {totals['campaigns']}; קבלות פרסום: {totals['published_receipts']}; אומתו חיים: {totals['verified_live']}; תקלות: {totals['failures']}; קישורים חסרים: {totals['missing_urls']}",
        "",
    ]
    for campaign in report["campaigns"]:
        lines.append(f"{campaign.get('title') or 'ללא כותרת'} — {campaign.get('status')}")
        for destination in campaign["destinations"]:
            status = destination.get("status")
            if status == "failed":
                diagnosis = destination["diagnosis"]
                lines.append(f"  תקלה: {destination.get('name')} — {diagnosis['reason']}")
                lines.append(f"  פעולה: {diagnosis['action']}")
            elif status in SUCCESS_STATUSES:
                verification = destination.get("verification", {}).get("state", "not_checked")
                lines.append(f"  {destination.get('name')}: {status}; אימות={verification}; {destination.get('url', '')}")
        lines.append("")
    if not report["campaigns"]:
        lines.append("לא נמצאו קמפיינים בחלון הזמן שנבדק.")
    return "\n".join(lines)


def send_email(report):
    recipient = os.environ["PUBLICATION_EMAIL_TO"]
    username = os.environ["PUBLICATION_EMAIL_GMAIL_USERNAME"]
    password = os.environ["PUBLICATION_EMAIL_GMAIL_APP_PASSWORD"]
    text_body = render_email(report)
    failures = report["totals"]["failures"] + report["totals"]["missing_urls"]
    message = EmailMessage()
    message["From"] = username
    message["To"] = recipient
    message["Subject"] = f"דוח יומי ניטור פרסומים — {failures} תקלות — {report['generated_at'][:10]}"
    message.set_content(text_body)
    message.add_alternative(f"<html><body dir='rtl'><pre style='white-space:pre-wrap'>{html.escape(text_body)}</pre></body></html>", subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=30)
    parser.add_argument("--output", default="publication_watchdog_report.json")
    parser.add_argument("--send-email", action="store_true")
    args = parser.parse_args()
    report = build_report(args.hours)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_email(report))
    if args.send_email:
        send_email(report)


if __name__ == "__main__":
    main()
