import json
import tempfile
import unittest
from pathlib import Path

from scripts.reputation_core.topic_ledger import (
    ledger_topic_values,
    record_topic_event,
    sync_repository_topics,
)


class TopicLedgerTests(unittest.TestCase):
    def test_ledger_never_truncates_and_deduplicates_repeated_sync_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topics.json"
            for index in range(75):
                record_topic_event(
                    path,
                    topic=f"נושא רפואי ייחודי {index}",
                    status="generation_started",
                    occurred_at=f"2026-01-{(index % 28) + 1:02d}T00:00:00+00:00",
                    source="test",
                )
            record_topic_event(
                path,
                topic="נושא רפואי ייחודי 0",
                status="generation_started",
                occurred_at="2026-02-01T00:00:00+00:00",
                source="test",
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["topics"]), 75)
        self.assertEqual(len(payload["topics"][0]["events"]), 1)

    def test_repository_sync_records_draft_approval_and_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            drafts = root / "content_drafts"
            campaigns = drafts / "campaigns"
            approvals = root / "approval_bundles"
            campaigns.mkdir(parents=True)
            approvals.mkdir()
            draft_path = drafts / "topic.md"
            draft_path.write_text(
                "<!--\ngenerated_at: 2026-01-01T00:00:00+00:00\n"
                "topic: נושא חדש\ncontent_stream: canonical_depth\n-->\n\n"
                "# כותרת חדשה\n",
                encoding="utf-8",
            )
            (approvals / "index.json").write_text(json.dumps({"bundles": [{
                "draft_path": "content_drafts/topic.md",
                "approval_id": "apr_1",
                "status": "awaiting_explicit_approval",
                "created_at": "2026-01-01T01:00:00+00:00",
            }]}), encoding="utf-8")
            (campaigns / "topic.json").write_text(json.dumps({
                "draft": "content_drafts/topic.md",
                "title": "כותרת חדשה",
                "status": "completed",
                "published_at": "2026-01-02T00:00:00+00:00",
                "approval_id": "apr_1",
                "destinations": [{
                    "status": "published", "url": "https://example.test/topic"
                }],
            }), encoding="utf-8")
            ledger = root / "data" / "topics.json"
            sync_repository_topics(root, ledger)
            sync_repository_topics(root, ledger)
            payload = json.loads(ledger.read_text(encoding="utf-8"))
            values = ledger_topic_values(ledger)
        self.assertEqual(values, ["נושא חדש", "כותרת חדשה"])
        statuses = [item["status"] for item in payload["topics"][0]["events"]]
        self.assertEqual(
            statuses,
            ["draft_ready", "awaiting_explicit_approval", "published"],
        )


if __name__ == "__main__":
    unittest.main()
