#!/usr/bin/env python3
"""Email one daily digest for newly reviewable P7 approval bundles."""
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
from urllib.parse import urlencode


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "approval_notifications.json"
DEFAULT_INDEX = ROOT / "approval_bundles" / "index.json"
DEFAULT_LEDGER = ROOT / "data" / "approval_email_notifications.json"


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _parse_time(value: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def approval_link(base_url: str, approval_id: str) -> str:
    return f"{base_url.rstrip('/')}?{urlencode({'approval_id': approval_id})}"


def _bundle_details(entry: dict, *, root: Path) -> dict:
    bundle_path = Path(str(entry.get("bundle_path") or ""))
    if not bundle_path.is_absolute():
        bundle_path = root / bundle_path
    bundle = _load_json(bundle_path, {})
    canonical = next(
        (
            target
            for target in bundle.get("targets", [])
            if target.get("target_id") in {"canonical_wix", "canonical_wordpress"}
        ),
        {},
    )
    payload = canonical.get("payload") or {}
    return {
        "title": payload.get("title") or bundle.get("objective") or "תוכן חדש",
        "asset": canonical.get("asset") or "יעד פרסום",
        "bundle_path": entry.get("bundle_path"),
    }


def pending_notifications(
    *,
    config: dict,
    index: dict,
    ledger: dict,
    root: Path = ROOT,
) -> list[dict]:
    if not config.get("enabled"):
        return []
    enabled_at = _parse_time(config.get("enabled_at"))
    sent = ledger.get("notifications", {})
    pending = []
    for entry in index.get("bundles", []):
        approval_id = str(entry.get("approval_id") or "")
        created_at = _parse_time(entry.get("created_at"))
        if not approval_id or approval_id in sent:
            continue
        if enabled_at and (not created_at or created_at < enabled_at):
            continue
        if (
            config.get("send_only_when_image_ready", True)
            and entry.get("image_status") != "ready"
        ):
            continue
        pending.append({
            **entry,
            **_bundle_details(entry, root=root),
            "approval_url": approval_link(config["dashboard_url"], approval_id),
        })
    return sorted(pending, key=lambda item: item.get("created_at", ""))


def build_message(item: dict, *, recipient: str, sender: str) -> EmailMessage:
    approval_id = item["approval_id"]
    title = str(item["title"])
    url = item["approval_url"]
    image_ready = item.get("image_status") == "ready"
    image_problem = str(item.get("image_selection_error") or "").strip()
    message = EmailMessage()
    message["Subject"] = (
        f"נדרש אישור פרסום: {title}"
        if image_ready
        else f"נדרשת החלטה על תמונה: {title}"
    )
    message["From"] = sender
    message["To"] = recipient
    message["Message-ID"] = f"<{approval_id}@dr-rofe-reputation-agent>"
    message["X-Approval-ID"] = approval_id
    if image_ready:
        lead = "נוצר תוכן חדש שממתין לאישור פרסום."
        action = "פתיחת מסך האישור"
        problem_line = ""
    else:
        lead = (
            "התוכן הוכן ונשמר, אך הסוכן לא הצליח לבחור לבדו צילום "
            "מורשה ורלוונטי. התוכן לא בוטל ולא סומן ככשל."
        )
        action = "פתיחת מסך ההחלטה ומתן פתרון לתמונה"
        problem_line = (
            f"בעיה: {image_problem}"
            if image_problem
            else "בעיה: נדרשת בחירת תמונה."
        )
    message.set_content(
        "\n".join(
            line
            for line in [
                lead,
                f"כותרת: {title}",
                f"יעד: {item['asset']}",
                problem_line,
                f"מזהה אישור: {approval_id}",
                "",
                f"{action}: {url}",
                "",
                "לא יתבצע פרסום ללא אישור P7 מפורש לתוכן המדויק.",
            ]
            if line or line == ""
        )
    )
    heading = "תוכן חדש ממתין לאישור" if image_ready else "נדרשת החלטה על תמונה"
    problem_html = (
        ""
        if image_ready
        else (
            "<p>התוכן הוכן ונשמר, אך הסוכן לא הצליח לבחור לבדו צילום "
            "מורשה ורלוונטי. התוכן לא בוטל ולא סומן ככשל.</p>"
            f"<p><strong>הבעיה:</strong> "
            f"{html.escape(image_problem or 'נדרשת בחירת תמונה.')}</p>"
        )
    )
    message.add_alternative(
        f"""<!doctype html>
<html lang="he" dir="rtl"><body style="font-family:Arial,sans-serif;line-height:1.6">
<h1>{heading}</h1>
<p><strong>{html.escape(title)}</strong></p>
<p>יעד: {html.escape(str(item['asset']))}</p>
{problem_html}
<p><a href="{html.escape(url, quote=True)}"
style="display:inline-block;background:#155eef;color:white;padding:12px 20px;
text-decoration:none;border-radius:6px">{html.escape(action)}</a></p>
<p style="color:#667085">מזהה: {html.escape(approval_id)}<br>
לא יתבצע פרסום ללא אישור P7 מפורש לתוכן המדויק.</p>
</body></html>""",
        subtype="html",
    )
    return message


def build_digest_message(
    items: list[dict], *, recipient: str, sender: str
) -> EmailMessage:
    """Build one message containing every pending decision in this run."""
    if not items:
        raise ValueError("At least one pending approval is required")
    if len(items) == 1:
        return build_message(items[0], recipient=recipient, sender=sender)

    approval_ids = [str(item["approval_id"]) for item in items]
    digest_id = hashlib.sha256("\n".join(approval_ids).encode()).hexdigest()[:24]
    image_decisions = sum(
        item.get("image_status") != "ready" for item in items
    )
    message = EmailMessage()
    message["Subject"] = f"מרכז המוניטין: {len(items)} החלטות ממתינות"
    message["From"] = sender
    message["To"] = recipient
    message["Message-ID"] = (
        f"<approval-digest-{digest_id}@dr-rofe-reputation-agent>"
    )
    message["X-Approval-Count"] = str(len(items))

    plain = [
        f"רוכזו עבורך {len(items)} החלטות שממתינות במרכז המוניטין.",
    ]
    if image_decisions:
        plain.append(f"מתוכן {image_decisions} דורשות החלטה על תמונה.")
    plain.append("")
    html_items = []
    for position, item in enumerate(items, 1):
        image_ready = item.get("image_status") == "ready"
        action = "אישור פרסום" if image_ready else "החלטה על תמונה"
        problem = str(item.get("image_selection_error") or "").strip()
        plain.extend([
            f"{position}. {item['title']}",
            f"   נדרש: {action}",
            f"   יעד: {item['asset']}",
        ])
        if problem:
            plain.append(f"   בעיה: {problem}")
        plain.extend([
            f"   מזהה: {item['approval_id']}",
            f"   פתיחה: {item['approval_url']}",
            "",
        ])
        problem_html = (
            f"<p><strong>בעיה:</strong> {html.escape(problem)}</p>"
            if problem else ""
        )
        html_items.append(
            f"<li style='margin-bottom:24px'><strong>{html.escape(str(item['title']))}</strong>"
            f"<br>נדרש: {html.escape(action)}"
            f"<br>יעד: {html.escape(str(item['asset']))}{problem_html}"
            f"<a href='{html.escape(str(item['approval_url']), quote=True)}'>פתיחת ההחלטה</a>"
            f"<br><small>מזהה: {html.escape(str(item['approval_id']))}</small></li>"
        )
    plain.append("לא יתבצע פרסום ללא אישור P7 מפורש לתוכן המדויק.")
    message.set_content("\n".join(plain))
    message.add_alternative(
        "<!doctype html><html lang='he' dir='rtl'><body "
        "style='font-family:Arial,sans-serif;line-height:1.6'>"
        f"<h1>{len(items)} החלטות ממתינות</h1>"
        f"<p>מתוכן {image_decisions} דורשות החלטה על תמונה.</p>"
        f"<ol>{''.join(html_items)}</ol>"
        "<p style='color:#667085'>לא יתבצע פרסום ללא אישור P7 מפורש "
        "לתוכן המדויק.</p></body></html>",
        subtype="html",
    )
    return message


def _smtp_send(message: EmailMessage, *, username: str, app_password: str) -> None:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(username, app_password)
        smtp.send_message(message)


def notify(
    *,
    config_path: Path = DEFAULT_CONFIG,
    index_path: Path = DEFAULT_INDEX,
    ledger_path: Path = DEFAULT_LEDGER,
    root: Path = ROOT,
    dry_run: bool = False,
    send_func=_smtp_send,
    now: datetime | None = None,
) -> list[dict]:
    config = _load_json(config_path, {})
    index = _load_json(index_path, {"bundles": []})
    ledger = _load_json(ledger_path, {"version": 1, "notifications": {}})
    pending = pending_notifications(
        config=config,
        index=index,
        ledger=ledger,
        root=root,
    )
    if dry_run:
        return pending
    username = os.environ.get(
        "WEEKLY_REPORT_GMAIL_USERNAME",
        config.get("sender_username", ""),
    ).strip()
    recipient = os.environ.get(
        "WEEKLY_REPORT_TO",
        config.get("recipient", ""),
    ).strip()
    app_password = os.environ.get(
        "WEEKLY_REPORT_GMAIL_APP_PASSWORD",
        "",
    ).replace(" ", "")
    if pending and (not username or not recipient or not app_password):
        raise RuntimeError("Gmail approval-notification credentials are incomplete")
    sent_at = (now or datetime.now(timezone.utc)).isoformat()
    if pending:
        message = build_digest_message(
            pending, recipient=recipient, sender=username
        )
        send_func(message, username=username, app_password=app_password)
    for item in pending:
        ledger.setdefault("notifications", {})[item["approval_id"]] = {
            "sent_at": sent_at,
            "recipient": recipient,
            "approval_url": item["approval_url"],
            "bundle_path": item.get("bundle_path"),
        }
    if pending:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return pending


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    notified = notify(
        config_path=args.config,
        index_path=args.index,
        ledger_path=args.ledger,
        dry_run=args.dry_run,
    )
    for item in notified:
        print(f"{item['approval_id']}\t{item['approval_url']}")
    print(f"Approval notifications: {len(notified)}")


if __name__ == "__main__":
    main()
