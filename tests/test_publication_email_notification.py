import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.publication_email_notification import build_message, notify


class PublicationEmailNotificationTests(unittest.TestCase):
    def test_success_email_contains_each_verified_publication_link(self):
        result = {
            "approval_id": "apr_success",
            "title": "כותרת מאושרת",
            "status": "completed",
            "destinations": [
                {
                    "name": "guyrofe.com",
                    "status": "published",
                    "url": "https://guyrofe.com/article",
                },
                {
                    "name": "Facebook",
                    "status": "published",
                    "url": "https://facebook.com/post/1",
                },
                {
                    "name": "Editorial image",
                    "status": "hosted",
                    "url": "https://example.com/image.jpg",
                },
            ],
        }
        message = build_message(
            result,
            recipient="owner@example.com",
            sender="sender@example.com",
            dashboard_url="https://approval.example",
        )
        plain = message.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(message["Subject"], "אישור פרסום: כותרת מאושרת")
        self.assertIn("https://guyrofe.com/article", plain)
        self.assertIn("https://facebook.com/post/1", plain)
        self.assertNotIn("https://example.com/image.jpg", plain)

    def test_partial_email_reports_successes_and_failures(self):
        result = {
            "approval_id": "apr_partial",
            "title": "כותרת",
            "status": "completed_with_errors",
            "destinations": [
                {
                    "name": "Website",
                    "status": "published",
                    "url": "https://example.com/post",
                },
                {
                    "name": "Instagram",
                    "status": "failed",
                    "detail": "provider unavailable",
                },
            ],
        }
        message = build_message(
            result,
            recipient="owner@example.com",
            sender="sender@example.com",
            dashboard_url="https://approval.example",
        )
        plain = message.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("הפרסום הושלם עם תקלות", message["Subject"])
        self.assertIn("https://example.com/post", plain)
        self.assertIn("provider unavailable", plain)

    def test_notification_is_sent_once_and_records_exact_urls(self):
        sent = []
        result = {
            "approval_id": "apr_once",
            "title": "כותרת",
            "status": "completed",
            "destinations": [{
                "name": "Website",
                "status": "published",
                "url": "https://example.com/post",
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "publication-emails.json"

            def fake_send(message, **_kwargs):
                sent.append(message)

            first = notify(
                result,
                ledger_path=ledger,
                recipient="owner@example.com",
                username="sender@example.com",
                app_password="secret",
                dashboard_url="https://approval.example",
                send_func=fake_send,
                now=datetime(2026, 8, 2, 16, 30, tzinfo=timezone.utc),
            )
            result["published_at"] = "2026-08-02T16:35:00+00:00"
            second = notify(
                result,
                ledger_path=ledger,
                recipient="owner@example.com",
                username="sender@example.com",
                app_password="secret",
                dashboard_url="https://approval.example",
                send_func=fake_send,
            )
            saved = json.loads(ledger.read_text(encoding="utf-8"))
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(sent), 1)
        record = next(iter(saved["notifications"].values()))
        self.assertEqual(record["state"], "success")
        self.assertEqual(record["urls"], ["https://example.com/post"])

    def test_workflow_sends_email_before_committing_delivery_ledger(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "publish_approved.yml"
        ).read_text(encoding="utf-8")
        email_step = workflow.index("Email publication result with verified links")
        commit_step = workflow.index("Commit campaign receipt and email delivery record")
        self.assertLess(email_step, commit_step)
        self.assertIn("publication_email_notification.py", workflow)
        self.assertIn("WEEKLY_REPORT_GMAIL_APP_PASSWORD", workflow)
        self.assertIn("data/publication_email_notifications.json", workflow)


if __name__ == "__main__":
    unittest.main()
