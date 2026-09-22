#!/usr/bin/env python3
"""Notify once when a signed approval expires before a campaign result exists."""
import argparse
import html
import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


def notify(response_path, ledger_path, *, send=True):
    response = json.loads(Path(response_path).read_text(encoding="utf-8"))
    expired = response.get("expired_approvals") or []
    try:
        ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        ledger = {"version": 1, "notifications": {}}
    notifications = ledger.setdefault("notifications", {})
    pending = [
        item for item in expired
        if item.get("approval_id") and item.get("approved_at")
        and f"expired:{item['approval_id']}:{item['approved_at']}" not in notifications
    ]
    if not pending:
        return 0
    username = os.environ.get("PUBLICATION_EMAIL_GMAIL_USERNAME", "").strip()
    recipient = os.environ.get("PUBLICATION_EMAIL_TO", "").strip()
    password = os.environ.get("PUBLICATION_EMAIL_GMAIL_APP_PASSWORD", "").replace(" ", "")
    if send and (not username or not recipient or not password):
        raise RuntimeError("Expiration email credentials are incomplete")
    message = EmailMessage()
    message["From"] = username or "guyrofe@gmail.com"
    message["To"] = recipient or "guyrofe@gmail.com"
    message["Subject"] = f"אישורי פרסום שפגו ללא פרסום מתועד: {len(pending)}"
    prefix = "האישורים הבאים פגו. אין עבורם דוח פרסום תקין, ולא יתחיל פרסום על סמך האישורים האלה. נדרש אישור חדש לכל טיוטה."
    rows = [f"• {item.get('title') or item.get('draft_path')} (אושר: {item['approved_at']})" for item in pending]
    dashboard = "https://dr-rofe-reputation-center.guyrofe.chatgpt.site"
    message.set_content("\n".join([prefix, "", *rows, "", f"מרכז האישור: {dashboard}"]))
    message.add_alternative(
        "<html lang='he' dir='rtl'><body style='font-family:Arial,sans-serif'>"
        f"<p>{html.escape(prefix)}</p><ul>"
        + "".join(f"<li>{html.escape(str(item.get('title') or item.get('draft_path')))} "
                  f"(אושר: {html.escape(item['approved_at'])})</li>" for item in pending)
        + f"</ul><p><a href='{dashboard}'>מרכז האישור</a></p></body></html>",
        subtype="html",
    )
    if not send:
        return len(pending)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, password)
        smtp.send_message(message)
    sent_at = datetime.now(timezone.utc).isoformat()
    for item in pending:
        notifications[f"expired:{item['approval_id']}:{item['approved_at']}"] = {
            "sent_at": sent_at,
            "recipient": recipient,
            "approval_id": item["approval_id"],
            "state": "expired",
            "subject": message["Subject"],
        }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=Path("data/publication_email_notifications.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    count = notify(args.response, args.ledger, send=not args.dry_run)
    print(f"Expiration notices processed: {count}")


if __name__ == "__main__":
    main()
