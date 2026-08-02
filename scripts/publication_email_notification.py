#!/usr/bin/env python3
"""Email one idempotent publication result after an approved campaign runs."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT / "data" / "publication_email_notifications.json"
DEFAULT_RECIPIENT = "guyrofe@gmail.com"
LINK_STATUSES = {"published", "skipped_duplicate"}
FAILURE_STATUSES = {"failed", "blocked", "reconciliation_required"}


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _publication_state(result: dict) -> tuple[str, list[dict], list[dict]]:
    destinations = result.get("destinations") or []
    links = [
        item
        for item in destinations
        if item.get("status") in LINK_STATUSES and item.get("url")
    ]
    failures = [
        item for item in destinations if item.get("status") in FAILURE_STATUSES
    ]
    if links and not failures and result.get("status") == "completed":
        return "success", links, failures
    if links:
        return "partial", links, failures
    return "failed", links, failures


def _notification_key(result: dict) -> str:
    stable_result = {
        "approval_id": result.get("approval_id"),
        "title": result.get("title"),
        "status": result.get("status"),
        "destinations": result.get("destinations") or [],
    }
    fingerprint = hashlib.sha256(
        json.dumps(stable_result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"{result.get('approval_id') or 'unknown'}:{fingerprint}"


def build_message(
    result: dict,
    *,
    recipient: str,
    sender: str,
    dashboard_url: str,
) -> EmailMessage:
    state, links, failures = _publication_state(result)
    title = str(result.get("title") or "תוכן מאושר")
    subjects = {
        "success": f"אישור פרסום: {title}",
        "partial": f"הפרסום הושלם עם תקלות: {title}",
        "failed": f"הפרסום נכשל: {title}",
    }
    headings = {
        "success": "הפרסום הושלם בהצלחה",
        "partial": "הפרסום הושלם בחלק מהיעדים",
        "failed": "הפרסום לא הושלם",
    }
    message = EmailMessage()
    message["Subject"] = subjects[state]
    message["From"] = sender
    message["To"] = recipient
    message_id = _notification_key(result).replace(":", ".")
    message["Message-ID"] = f"<{message_id}@dr-rofe-reputation-agent>"
    message["X-Approval-ID"] = str(result.get("approval_id") or "unknown")

    text_lines = [headings[state], f"כותרת: {title}", ""]
    if links:
        text_lines.append("קישורים לנכסים שפורסמו:")
        text_lines.extend(
            f"- {item.get('name') or 'יעד'}: {item['url']}" for item in links
        )
    else:
        text_lines.append("לא התקבל קישור מאומת לנכס שפורסם.")
    if failures:
        text_lines.extend(["", "יעדים שנכשלו או נחסמו:"])
        text_lines.extend(
            f"- {item.get('name') or 'יעד'}: "
            f"{item.get('detail') or item.get('status')}"
            for item in failures
        )
    text_lines.extend(["", f"פתיחת מרכז האישור: {dashboard_url}"])
    message.set_content("\n".join(text_lines) + "\n")

    link_rows = "".join(
        "<li>"
        f"<strong>{html.escape(str(item.get('name') or 'יעד'))}:</strong> "
        f"<a href=\"{html.escape(str(item['url']), quote=True)}\">"
        "פתיחת הפרסום</a></li>"
        for item in links
    ) or "<li>לא התקבל קישור מאומת לנכס שפורסם.</li>"
    failure_rows = "".join(
        "<li>"
        f"<strong>{html.escape(str(item.get('name') or 'יעד'))}:</strong> "
        f"{html.escape(str(item.get('detail') or item.get('status')))}"
        "</li>"
        for item in failures
    )
    failure_section = (
        f"<h2>יעדים שנכשלו או נחסמו</h2><ul>{failure_rows}</ul>"
        if failure_rows
        else ""
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="he" dir="rtl"><body style="font-family:Arial,sans-serif;line-height:1.6">
<h1>{headings[state]}</h1>
<p><strong>{html.escape(title)}</strong></p>
<h2>קישורים לנכסים שפורסמו</h2>
<ul>{link_rows}</ul>
{failure_section}
<p><a href="{html.escape(dashboard_url, quote=True)}">פתיחת מרכז האישור</a></p>
<p style="color:#667085">מזהה אישור: {html.escape(str(result.get('approval_id') or 'unknown'))}</p>
</body></html>""",
        subtype="html",
    )
    return message


def _smtp_send(message: EmailMessage, *, username: str, app_password: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, app_password)
        smtp.send_message(message)


def notify(
    result: dict,
    *,
    ledger_path: Path = DEFAULT_LEDGER,
    recipient: str,
    username: str,
    app_password: str,
    dashboard_url: str,
    send_func=_smtp_send,
    now: datetime | None = None,
    dry_run: bool = False,
) -> bool:
    ledger = _load_json(ledger_path, {"version": 1, "notifications": {}})
    key = _notification_key(result)
    if key in ledger.get("notifications", {}):
        return False
    message = build_message(
        result,
        recipient=recipient,
        sender=username,
        dashboard_url=dashboard_url,
    )
    if dry_run:
        return True
    if not username or not recipient or not app_password:
        raise RuntimeError("Publication email credentials are incomplete")
    send_func(message, username=username, app_password=app_password)
    state, links, _failures = _publication_state(result)
    ledger.setdefault("notifications", {})[key] = {
        "sent_at": (now or datetime.now(timezone.utc)).isoformat(),
        "recipient": recipient,
        "approval_id": result.get("approval_id"),
        "state": state,
        "subject": message["Subject"],
        "urls": [item["url"] for item in links],
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def _fallback_result(draft_path: str, approval_id: str) -> dict:
    title = Path(draft_path).stem if draft_path else "תוכן מאושר"
    return {
        "draft": draft_path,
        "title": title,
        "status": "failed",
        "approval_id": approval_id or None,
        "destinations": [{
            "name": "Campaign",
            "status": "failed",
            "detail": "הפרסום נכשל לפני שנוצר דוח תוצאות.",
        }],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--draft-path", default="")
    parser.add_argument("--approval-id", default="")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument(
        "--dashboard-url",
        default="https://dr-rofe-reputation-center.guyrofe.chatgpt.site",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    fallback = _fallback_result(args.draft_path, args.approval_id)
    result = _load_json(args.result, fallback)
    if args.approval_id and result.get("approval_id") != args.approval_id:
        result = fallback
    username = os.environ.get(
        "PUBLICATION_EMAIL_GMAIL_USERNAME",
        os.environ.get("WEEKLY_REPORT_GMAIL_USERNAME", DEFAULT_RECIPIENT),
    ).strip()
    recipient = os.environ.get(
        "PUBLICATION_EMAIL_TO",
        os.environ.get("WEEKLY_REPORT_TO", DEFAULT_RECIPIENT),
    ).strip()
    app_password = os.environ.get(
        "PUBLICATION_EMAIL_GMAIL_APP_PASSWORD",
        os.environ.get("WEEKLY_REPORT_GMAIL_APP_PASSWORD", ""),
    ).replace(" ", "")
    sent = notify(
        result,
        ledger_path=args.ledger,
        recipient=recipient,
        username=username,
        app_password=app_password,
        dashboard_url=args.dashboard_url,
        dry_run=args.dry_run,
    )
    print("Publication email sent" if sent else "Publication email already sent")


if __name__ == "__main__":
    main()
