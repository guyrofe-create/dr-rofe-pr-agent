#!/usr/bin/env python3
"""Notify once when a signed approval expires before publication is proven."""
import argparse
import html
import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGNS_DIR = ROOT / "content_drafts" / "campaigns"
DEFAULT_BUNDLES_DIR = ROOT / "approval_bundles"
PUBLICATION_STATUSES = {"published", "skipped_duplicate"}


def _load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return default


def _normalise_draft_path(value):
    return str(value or "").strip().removeprefix("./")


def _expired_draft_path(item, bundles_dir):
    draft_path = _normalise_draft_path(
        item.get("draft_path") or item.get("source_draft")
    )
    if draft_path:
        return draft_path
    approval_id = str(item.get("approval_id") or "").strip()
    if not approval_id:
        return ""
    bundle = _load_json(Path(bundles_dir) / f"{approval_id}.json", {}) or {}
    return _normalise_draft_path(bundle.get("source_draft"))


def _published_result_by_draft(campaigns_dir):
    """Return the strongest public-publication evidence for each source draft."""
    published = {}
    for result_path in sorted(Path(campaigns_dir).glob("*.json")):
        result = _load_json(result_path, {}) or {}
        draft_path = _normalise_draft_path(
            result.get("draft") or result.get("draft_path")
        )
        if not draft_path:
            continue
        destinations = result.get("destinations") or []
        urls = [
            str(destination["url"])
            for destination in destinations
            if destination.get("status") in PUBLICATION_STATUSES
            and destination.get("url")
        ]
        if urls:
            try:
                recorded_result_path = str(result_path.relative_to(ROOT))
            except ValueError:
                recorded_result_path = str(result_path)
            published[draft_path] = {
                "approval_id": result.get("approval_id"),
                "result_path": recorded_result_path,
                "urls": urls,
            }
    return published


def _write_ledger(ledger_path, ledger):
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def notify(
    response_path,
    ledger_path,
    *,
    campaigns_dir=DEFAULT_CAMPAIGNS_DIR,
    bundles_dir=DEFAULT_BUNDLES_DIR,
    send=True,
):
    response = json.loads(Path(response_path).read_text(encoding="utf-8"))
    expired = response.get("expired_approvals") or []
    try:
        ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        ledger = {"version": 1, "notifications": {}}
    notifications = ledger.setdefault("notifications", {})
    published_by_draft = _published_result_by_draft(campaigns_dir)
    pending = []
    superseded = []
    for item in expired:
        if not item.get("approval_id") or not item.get("approved_at"):
            continue
        notification_key = (
            f"expired:{item['approval_id']}:{item['approved_at']}"
        )
        if notification_key in notifications:
            continue
        draft_path = _expired_draft_path(item, bundles_dir)
        published_result = published_by_draft.get(draft_path)
        if published_result:
            superseded.append(
                (notification_key, item, draft_path, published_result)
            )
        else:
            pending.append(item)
    if not pending and not superseded:
        return 0
    if not send:
        return len(pending)
    username = os.environ.get("PUBLICATION_EMAIL_GMAIL_USERNAME", "").strip()
    recipient = os.environ.get("PUBLICATION_EMAIL_TO", "").strip()
    password = os.environ.get(
        "PUBLICATION_EMAIL_GMAIL_APP_PASSWORD", ""
    ).replace(" ", "")
    if pending and (not username or not recipient or not password):
        raise RuntimeError("Expiration email credentials are incomplete")
    sent_at = datetime.now(timezone.utc).isoformat()
    for key, item, draft_path, result in superseded:
        notifications[key] = {
            "recorded_at": sent_at,
            "approval_id": item["approval_id"],
            "state": "superseded_published",
            "draft_path": draft_path,
            "published_approval_id": result.get("approval_id"),
            "campaign_result": result["result_path"],
            "urls": result["urls"],
        }
    if pending:
        message = EmailMessage()
        message["From"] = username or "guyrofe@gmail.com"
        message["To"] = recipient or "guyrofe@gmail.com"
        message["Subject"] = (
            f"אישורי פרסום שפגו, מצב הפרסום טעון בדיקה: {len(pending)}"
        )
        prefix = "האישורים הבאים פגו, ולא נמצא עבורם דוח פרסום תקין במערכת. ייתכן שהתוכן כבר פורסם באתר היעד; ההודעה אינה קובעת שלא פורסם. יש לבדוק את יעד הפרסום. אישור שפג לא יאפשר פרסום נוסף. אם התוכן כבר פורסם, אין צורך לאשר אותו שוב. אם לא פורסם וברצונך לפרסמו, נדרש אישור חדש."
        rows = [
            f"• {item.get('title') or item.get('draft_path')} "
            f"(אושר: {item['approved_at']})"
            for item in pending
        ]
        dashboard = "https://dr-rofe-reputation-center.guyrofe.chatgpt.site"
        message.set_content(
            "\n".join([prefix, "", *rows, "", f"מרכז האישור: {dashboard}"])
        )
        message.add_alternative(
            "<html lang='he' dir='rtl'><body style='font-family:Arial,sans-serif'>"
            f"<p>{html.escape(prefix)}</p><ul>"
            + "".join(
                f"<li>{html.escape(str(item.get('title') or item.get('draft_path')))} "
                f"(אושר: {html.escape(item['approved_at'])})</li>"
                for item in pending
            )
            + f"</ul><p><a href='{dashboard}'>מרכז האישור</a></p></body></html>",
            subtype="html",
        )
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
            smtp.login(username, password)
            smtp.send_message(message)
        for item in pending:
            notifications[
                f"expired:{item['approval_id']}:{item['approved_at']}"
            ] = {
                "sent_at": sent_at,
                "recipient": recipient,
                "approval_id": item["approval_id"],
                "state": "expired",
                "subject": message["Subject"],
            }
    _write_ledger(Path(ledger_path), ledger)
    return len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument(
        "--ledger",
        type=Path,
        default=Path("data/publication_email_notifications.json"),
    )
    parser.add_argument("--campaigns-dir", type=Path, default=DEFAULT_CAMPAIGNS_DIR)
    parser.add_argument("--bundles-dir", type=Path, default=DEFAULT_BUNDLES_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = notify(
        args.response,
        args.ledger,
        campaigns_dir=args.campaigns_dir,
        bundles_dir=args.bundles_dir,
        send=not args.dry_run,
    )
    print(f"Expiration notices processed: {count}")


if __name__ == "__main__":
    main()
