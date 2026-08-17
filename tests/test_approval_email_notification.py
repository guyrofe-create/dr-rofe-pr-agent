import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.approval_email_notification import (
    build_digest_message,
    build_message,
    notify,
)


class ApprovalEmailNotificationTests(unittest.TestCase):
    def test_digest_combines_multiple_pending_decisions(self):
        items = [
            {
                "approval_id": "apr_one",
                "title": "כותרת ראשונה",
                "asset": "example.com",
                "approval_url": "https://approval.example?approval_id=apr_one",
                "image_status": "ready",
            },
            {
                "approval_id": "apr_two",
                "title": "כותרת שנייה",
                "asset": "example.co.il",
                "approval_url": "https://approval.example?approval_id=apr_two",
                "image_status": "awaiting_replacement",
                "image_selection_error": "נדרשת תמונה חלופית",
            },
        ]
        message = build_digest_message(
            items, recipient="owner@example.com", sender="sender@example.com"
        )
        plain = message.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(message["Subject"], "מרכז המוניטין: 2 החלטות ממתינות")
        self.assertIn("כותרת ראשונה", plain)
        self.assertIn("כותרת שנייה", plain)
        self.assertIn("נדרשת תמונה חלופית", plain)

    def test_owner_decision_email_contains_problem_and_direct_link(self):
        message = build_message(
            {
                "approval_id": "apr_waiting",
                "title": "כאבי מחזור",
                "asset": "drguyrofe.co.il",
                "approval_url": "https://approval.example?approval_id=apr_waiting",
                "image_status": "awaiting_replacement",
                "image_selection_error": "לא נמצא צילום מורשה מתאים",
            },
            recipient="owner@example.com",
            sender="sender@example.com",
        )
        plain = message.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(message["Subject"], "נדרשת החלטה על תמונה: כאבי מחזור")
        self.assertIn("לא נמצא צילום מורשה מתאים", plain)
        self.assertIn("התוכן לא בוטל ולא סומן ככשל", plain)
        self.assertIn(
            "https://approval.example?approval_id=apr_waiting",
            plain,
        )

    def test_sends_once_with_direct_approval_link(self):
        sent = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approval_bundles").mkdir()
            (root / "data").mkdir()
            config = root / "config.json"
            index = root / "approval_bundles" / "index.json"
            ledger = root / "data" / "notifications.json"
            bundle_path = root / "approval_bundles" / "apr_new.json"
            config.write_text(json.dumps({
                "enabled": True,
                "enabled_at": "2026-07-30T07:45:00Z",
                "dashboard_url": "https://approval.example",
                "recipient": "owner@example.com",
                "sender_username": "sender@example.com",
                "send_only_when_image_ready": True,
            }), encoding="utf-8")
            bundle_path.write_text(json.dumps({
                "targets": [{
                    "target_id": "canonical_wix",
                    "asset": "archive.example",
                    "payload": {"title": "תמליל פרק"},
                }]
            }), encoding="utf-8")
            index.write_text(json.dumps({"bundles": [{
                "approval_id": "apr_new",
                "bundle_path": "approval_bundles/apr_new.json",
                "created_at": "2026-07-30T08:00:00Z",
                "image_status": "ready",
            }]}), encoding="utf-8")

            def fake_send(message, **_kwargs):
                sent.append(message)

            old_password = __import__("os").environ.get(
                "WEEKLY_REPORT_GMAIL_APP_PASSWORD"
            )
            __import__("os").environ["WEEKLY_REPORT_GMAIL_APP_PASSWORD"] = "test"
            try:
                first = notify(
                    config_path=config,
                    index_path=index,
                    ledger_path=ledger,
                    root=root,
                    send_func=fake_send,
                    now=datetime(2026, 7, 30, 8, 5, tzinfo=timezone.utc),
                )
                second = notify(
                    config_path=config,
                    index_path=index,
                    ledger_path=ledger,
                    root=root,
                    send_func=fake_send,
                )
            finally:
                if old_password is None:
                    __import__("os").environ.pop(
                        "WEEKLY_REPORT_GMAIL_APP_PASSWORD", None
                    )
                else:
                    __import__("os").environ[
                        "WEEKLY_REPORT_GMAIL_APP_PASSWORD"
                    ] = old_password
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(sent), 1)
        self.assertIn(
            "https://approval.example?approval_id=apr_new",
            sent[0].get_body(preferencelist=("plain",)).get_content(),
        )

    def test_multiple_items_are_sent_as_one_email_and_all_recorded(self):
        sent = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "approval_bundles").mkdir()
            (root / "data").mkdir()
            config = root / "config.json"
            index = root / "approval_bundles" / "index.json"
            ledger = root / "data" / "notifications.json"
            config.write_text(json.dumps({
                "enabled": True,
                "enabled_at": "2026-07-30T07:45:00Z",
                "dashboard_url": "https://approval.example",
                "recipient": "owner@example.com",
                "sender_username": "sender@example.com",
                "send_only_when_image_ready": False,
            }), encoding="utf-8")
            entries = []
            for approval_id in ("apr_one", "apr_two"):
                bundle_path = root / "approval_bundles" / f"{approval_id}.json"
                bundle_path.write_text(json.dumps({
                    "objective": approval_id,
                    "targets": [],
                }), encoding="utf-8")
                entries.append({
                    "approval_id": approval_id,
                    "bundle_path": f"approval_bundles/{approval_id}.json",
                    "created_at": "2026-07-30T08:00:00Z",
                    "image_status": "ready",
                })
            index.write_text(json.dumps({"bundles": entries}), encoding="utf-8")

            def fake_send(message, **_kwargs):
                sent.append(message)

            old_password = __import__("os").environ.get(
                "WEEKLY_REPORT_GMAIL_APP_PASSWORD"
            )
            __import__("os").environ["WEEKLY_REPORT_GMAIL_APP_PASSWORD"] = "test"
            try:
                notified = notify(
                    config_path=config,
                    index_path=index,
                    ledger_path=ledger,
                    root=root,
                    send_func=fake_send,
                )
            finally:
                if old_password is None:
                    __import__("os").environ.pop(
                        "WEEKLY_REPORT_GMAIL_APP_PASSWORD", None
                    )
                else:
                    __import__("os").environ[
                        "WEEKLY_REPORT_GMAIL_APP_PASSWORD"
                    ] = old_password

            recorded = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertEqual(len(notified), 2)
        self.assertEqual(len(sent), 1)
        self.assertEqual(
            set(recorded["notifications"]), {"apr_one", "apr_two"}
        )
