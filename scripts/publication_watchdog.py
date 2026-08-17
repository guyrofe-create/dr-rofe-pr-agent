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
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = PROJECT_ROOT / "content_drafts" / "campaigns"
BUNDLE_ROOT = PROJECT_ROOT / "approval_bundles"
DRAFT_INDEX = PROJECT_ROOT / "content_drafts" / "index.json"
BUNDLE_INDEX = BUNDLE_ROOT / "index.json"
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
    if name == "Instagram" and (
        "does not have permission" in probe
        or "oauth" in probe
        or "code=10" in probe
    ):
        return {
            "category": "instagram_permission_required",
            "reason": "Meta rejected the Instagram request because the connected app or token lacks the required permission.",
            "action": "Repair the Instagram professional-account permission or token before an explicitly approved retry; changing the image will not fix this error.",
        }
    if name == "Instagram" and (
        "media container" in probe
        or "unsupported image" in probe
        or "image format" in probe
        or "aspect ratio" in probe
    ):
        return {
            "category": "instagram_media_rejected",
            "reason": "Meta rejected the Instagram media container.",
            "action": "Use the approved JPEG square variant and retain Meta's structured error fields on the next attempt.",
        }
    if "invalid_grant" in probe and name in {
        "Blogger", "Google Business Profile"
    }:
        return {
            "category": "google_oauth_reauthorization_required",
            "reason": "Google rejected the stored OAuth refresh token because it expired or was revoked.",
            "action": "Reconnect Google once and replace the refresh token; repeated publication retries cannot repair an invalid grant.",
        }
    if any(marker in probe for marker in (
        "connecttimeout", "connectionerror", "readtimeout", "timed out",
        "temporary failure in name resolution", "max retries exceeded",
    )):
        return {
            "category": "transient_provider_connectivity",
            "reason": detail or "The provider could not be reached within the allowed time.",
            "action": "Probe the provider, reconcile the exact approved destination, and retry only through the existing approval-gated retry path.",
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


def verify_url(url, name, *, expected_title=None, request_get=requests.get):
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
        body = str(getattr(response, "text", "") or "")
        if expected_title and expected_title.casefold() in body.casefold():
            state = "verified_content"
        else:
            state = "live_url_content_unconfirmed"
    elif status in INCONCLUSIVE_HTTP and name in {"Facebook", "Instagram", "LinkedIn"}:
        state = "inconclusive_login_or_rate_limit"
    elif status in {404, 410}:
        state = "missing"
    else:
        state = "http_error"
    return {"state": state, "http_status": status, "final_url": response.url}


def load_bundle(approval_id):
    if not approval_id:
        return None
    path = BUNDLE_ROOT / f"{approval_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def expected_target_ids(bundle):
    return {
        target.get("target_id")
        for target in (bundle or {}).get("targets", [])
        if target.get("target_id")
    }


def normalized_destination_name(value):
    name = str(value or "").casefold().strip()
    name = re.sub(r"^https?://", "", name).split("/", 1)[0]
    return re.sub(r"^www\.", "", name)


def match_destination_target(destination, bundle):
    explicit = destination.get("target_id")
    if explicit:
        return explicit
    name = normalized_destination_name(destination.get("name"))
    matches = []
    for target in (bundle or {}).get("targets", []):
        platform = normalized_destination_name(target.get("platform"))
        asset = normalized_destination_name(target.get("asset"))
        if name in {platform, asset} or (asset and asset in name):
            matches.append(target.get("target_id"))
    return matches[0] if len(set(matches)) == 1 else None


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


def audit_pipeline(hours, now):
    cutoff = now - timedelta(hours=hours)
    drafts = load_index_items(DRAFT_INDEX, "drafts")
    bundles = load_index_items(BUNDLE_INDEX, "bundles")
    recent_drafts = [item for item in drafts if (parse_time(item.get("generated_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    recent_bundles = [item for item in bundles if (parse_time(item.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]
    bundled_drafts = {item.get("draft_path") for item in bundles}
    grace = now - timedelta(hours=2)
    stalled = [
        item.get("path") or item.get("draft_path")
        for item in recent_drafts
        if (item.get("path") or item.get("draft_path")) not in bundled_drafts
        and (parse_time(item.get("generated_at")) or now) < grace
    ]
    return {
        "recent_drafts": len(recent_drafts),
        "recent_approval_bundles": len(recent_bundles),
        "awaiting_explicit_approval": sum(
            1 for item in recent_bundles
            if not any(campaign.get("approval_id") == item.get("approval_id") for _, campaign in load_recent_campaigns(hours, now=now))
        ),
        "stalled_drafts_without_bundle": [item for item in stalled if item],
    }


def load_index_items(path, key):
    try:
        return json.loads(path.read_text(encoding="utf-8")).get(key, [])
    except (OSError, ValueError, TypeError):
        return []


def build_report(hours=30, *, now=None, request_get=requests.get):
    now = now or datetime.now(timezone.utc)
    campaign_reports = []
    totals = {
        "campaigns": 0, "intended_targets": 0, "receipt_confirmed": 0,
        "content_verified": 0, "inconclusive": 0, "failures": 0,
        "missing_urls": 0, "missing_intended_targets": 0,
        "unfulfilled_intended_targets": 0,
        "missing_approval_bundles": 0,
    }
    for path, campaign in load_recent_campaigns(hours, now=now):
        bundle = load_bundle(campaign.get("approval_id"))
        if campaign.get("approval_id") and not bundle:
            totals["missing_approval_bundles"] += 1
        expected = expected_target_ids(bundle)
        matched = set()
        totals["intended_targets"] += len(expected)
        item = {
            "receipt": path.relative_to(PROJECT_ROOT).as_posix(),
            "title": campaign.get("title"),
            "status": campaign.get("status"),
            "published_at": campaign.get("published_at"),
            "approval_id": campaign.get("approval_id"),
            "approval_bundle_found": bool(bundle),
            "expected_target_ids": sorted(expected),
            "destinations": [],
        }
        totals["campaigns"] += 1
        for destination in campaign.get("destinations", []):
            current = dict(destination)
            target_id = match_destination_target(current, bundle)
            if target_id:
                current["matched_target_id"] = target_id
                matched.add(target_id)
            if current.get("status") in SUCCESS_STATUSES:
                totals["receipt_confirmed"] += 1
                if current.get("url"):
                    current["verification"] = verify_url(
                        current["url"], current.get("name", ""),
                        expected_title=campaign.get("title"), request_get=request_get
                    )
                    if current["verification"]["state"] == "verified_content":
                        totals["content_verified"] += 1
                    elif current["verification"]["state"] in {
                        "live_url_content_unconfirmed",
                        "inconclusive_login_or_rate_limit",
                    }:
                        totals["inconclusive"] += 1
                    if current["verification"]["state"] == "missing":
                        totals["missing_urls"] += 1
                else:
                    current["verification"] = {"state": "receipt_missing_url"}
                    totals["missing_urls"] += 1
            elif current.get("status") == "failed":
                totals["failures"] += 1
                current["diagnosis"] = classify_failure(current)
            elif target_id in expected:
                current["verification"] = {"state": "approved_target_not_published"}
                totals["unfulfilled_intended_targets"] += 1
            item["destinations"].append(current)
        missing_targets = sorted(expected - matched)
        item["missing_intended_target_ids"] = missing_targets
        totals["missing_intended_targets"] += len(missing_targets)
        campaign_reports.append(item)
    pipeline = audit_pipeline(hours, now)
    hard_failures = (
        totals["failures"] + totals["missing_urls"]
        + totals["missing_intended_targets"]
        + totals["unfulfilled_intended_targets"]
        + totals["missing_approval_bundles"]
        + len(pipeline["stalled_drafts_without_bundle"])
    )
    control_status = "failure" if hard_failures else "degraded" if totals["inconclusive"] else "healthy"
    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "totals": totals,
        "control_status": control_status,
        "pipeline": pipeline,
        "campaigns": campaign_reports,
    }


def render_email(report):
    totals = report["totals"]
    lines = [
        f"דוח ניטור פרסומים יומי ({report['window_hours']} השעות האחרונות)",
        f"מצב בקרה: {report['control_status']}",
        f"קמפיינים: {totals['campaigns']}; יעדים מאושרים: {totals['intended_targets']}; "
        f"קבלות: {totals['receipt_confirmed']}; תוכן שאומת: {totals['content_verified']}; "
        f"לא חד-משמעי: {totals['inconclusive']}; תקלות: {totals['failures']}; "
        f"קישורים חסרים: {totals['missing_urls']}; יעדים חסרים: {totals['missing_intended_targets']}",
        f"יעדים מאושרים שלא פורסמו: {totals['unfulfilled_intended_targets']}",
        f"קבלות ללא חבילת אישור ניתנת לאימות: {totals['missing_approval_bundles']}",
        "",
        f"צנרת: טיוטות={report['pipeline']['recent_drafts']}; "
        f"חבילות אישור={report['pipeline']['recent_approval_bundles']}; "
        f"ממתינות לאישור={report['pipeline']['awaiting_explicit_approval']}; "
        f"טיוטות תקועות={len(report['pipeline']['stalled_drafts_without_bundle'])}",
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
        if campaign.get("missing_intended_target_ids"):
            lines.append("  יעדים שאושרו אך לא נמצאה עבורם קבלה: " + ", ".join(campaign["missing_intended_target_ids"]))
        if campaign.get("approval_id") and not campaign.get("approval_bundle_found"):
            lines.append("  חבילת האישור החתומה אינה זמינה לבקרת היעדים.")
        lines.append("")
    if not report["campaigns"]:
        lines.append("לא נמצאו קמפיינים בחלון הזמן שנבדק.")
    return "\n".join(lines)


def send_email(report):
    recipient = os.environ["PUBLICATION_EMAIL_TO"]
    username = os.environ["PUBLICATION_EMAIL_GMAIL_USERNAME"]
    password = os.environ["PUBLICATION_EMAIL_GMAIL_APP_PASSWORD"]
    text_body = render_email(report)
    failures = (
        report["totals"]["failures"] + report["totals"]["missing_urls"]
        + report["totals"]["missing_intended_targets"]
        + report["totals"]["unfulfilled_intended_targets"]
        + report["totals"]["missing_approval_bundles"]
    )
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
    parser.add_argument("--send-email-on-problem", action="store_true")
    args = parser.parse_args()
    report = build_report(args.hours)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(render_email(report))
    if args.send_email or (
        args.send_email_on_problem and report["control_status"] != "healthy"
    ):
        send_email(report)


if __name__ == "__main__":
    main()
