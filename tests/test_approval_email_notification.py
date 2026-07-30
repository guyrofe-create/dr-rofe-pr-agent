import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.approval_email_notification import notify


class ApprovalEmailNotificationTests(unittest.TestCase):
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

