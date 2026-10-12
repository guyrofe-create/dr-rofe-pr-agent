import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import notify_expired_approvals


class ExpiredApprovalNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.campaigns = self.root / "campaigns"
        self.bundles = self.root / "bundles"
        self.campaigns.mkdir()
        self.bundles.mkdir()
        self.response = self.root / "response.json"
        self.ledger = self.root / "ledger.json"

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_json(self, path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def _notify(self, *, send=True):
        return notify_expired_approvals.notify(
            self.response,
            self.ledger,
            campaigns_dir=self.campaigns,
            bundles_dir=self.bundles,
            send=send,
        )

    def test_suppresses_stale_approval_when_same_draft_was_published(self):
        expired_id = "apr_expired"
        draft = "content_drafts/topic.md"
        self._write_json(self.response, {"expired_approvals": [{
            "approval_id": expired_id,
            "approved_at": "2026-08-26T08:53:15Z",
            "title": "Published under a replacement approval",
        }]})
        self._write_json(self.bundles / f"{expired_id}.json", {
            "source_draft": draft,
        })
        self._write_json(self.campaigns / "topic.json", {
            "draft": draft,
            "approval_id": "apr_replacement",
            "status": "completed_with_errors",
            "destinations": [{
                "name": "Canonical",
                "status": "published",
                "url": "https://example.test/topic/",
            }, {
                "name": "Instagram",
                "status": "failed",
            }],
        })

        with patch("scripts.notify_expired_approvals.smtplib.SMTP_SSL") as smtp:
            count = self._notify()

        self.assertEqual(count, 0)
        smtp.assert_not_called()
        recorded = json.loads(self.ledger.read_text(encoding="utf-8"))
        entry = recorded["notifications"][
            f"expired:{expired_id}:2026-08-26T08:53:15Z"
        ]
        self.assertEqual(entry["state"], "superseded_published")
        self.assertEqual(entry["published_approval_id"], "apr_replacement")
        self.assertEqual(entry["draft_path"], draft)
        self.assertEqual(entry["urls"], ["https://example.test/topic/"])

    def test_does_not_treat_hosted_media_alone_as_publication(self):
        self._write_json(self.response, {"expired_approvals": [{
            "approval_id": "apr_expired",
            "approved_at": "2026-08-26T08:53:15Z",
            "draft_path": "content_drafts/topic.md",
        }]})
        self._write_json(self.campaigns / "topic.json", {
            "draft": "content_drafts/topic.md",
            "approval_id": "apr_other",
            "status": "failed",
            "destinations": [{
                "name": "Image",
                "status": "hosted",
                "url": "https://example.test/image.jpg",
            }],
        })

        self.assertEqual(self._notify(send=False), 1)
        self.assertFalse(self.ledger.exists())

    def test_dry_run_suppresses_published_item_without_writing_ledger(self):
        self._write_json(self.response, {"expired_approvals": [{
            "approval_id": "apr_expired",
            "approved_at": "2026-08-26T08:53:15Z",
            "draft_path": "./content_drafts/topic.md",
        }]})
        self._write_json(self.campaigns / "topic.json", {
            "draft": "content_drafts/topic.md",
            "approval_id": "apr_other",
            "destinations": [{
                "status": "skipped_duplicate",
                "url": "https://example.test/topic/",
            }],
        })

        self.assertEqual(self._notify(send=False), 0)
        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
