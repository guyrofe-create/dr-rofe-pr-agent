import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.weekly_email_report import collect_report, render_html, render_text


class WeeklyEmailReportTests(unittest.TestCase):
    def test_collects_verified_publications_actions_and_ai_cost(self):
        start = datetime(2026, 7, 22, tzinfo=timezone.utc)
        end = datetime(2026, 7, 29, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "content_drafts" / "campaigns").mkdir(parents=True)
            (root / "approval_bundles").mkdir()
            usage_dir = root / "data" / "ai_usage_events"
            usage_dir.mkdir(parents=True)
            (root / "data" / "reputation_history.json").write_text(
                json.dumps({"snapshots": [{
                    "date": "2026-07-28T06:00:00Z",
                    "orchestration": {"visibility_measurement": {
                        "asset_rank_changes": {
                            "status": "compared",
                            "current_observed_at": "2026-07-28T06:00:00Z",
                            "asset_count": 1,
                            "changed_count": 1,
                            "assets": [{
                                "platform": "LinkedIn",
                                "url": "https://linkedin.example/profile",
                                "previous_position_top10": 5,
                                "current_position_top10": 3,
                                "change": "improved",
                            }],
                        },
                    }},
                }]}),
                encoding="utf-8",
            )
            (root / "content_drafts" / "index.json").write_text(
                json.dumps({"drafts": [{
                    "title": "טיוטה רפואית",
                    "generated_at": "2026-07-28T09:00:00Z",
                }]}),
                encoding="utf-8",
            )
            (root / "approval_bundles" / "index.json").write_text(
                json.dumps({"bundles": [{
                    "approval_id": "apr_1",
                    "created_at": "2026-07-28T10:00:00Z",
                }]}),
                encoding="utf-8",
            )
            (root / "content_drafts" / "campaigns" / "index.json").write_text(
                json.dumps({"campaigns": [{
                    "title": "מאמר שפורסם",
                    "published_at": "2026-07-28T12:00:00Z",
                    "destinations": [
                        {
                            "name": "LinkedIn",
                            "status": "published",
                            "url": "https://linkedin.example/post",
                        },
                        {
                            "name": "Pinterest",
                            "status": "failed",
                            "detail": "not configured",
                        },
                    ],
                }]}),
                encoding="utf-8",
            )
            (usage_dir / "event.json").write_text(
                json.dumps({
                    "occurred_at": "2026-07-28T08:00:00Z",
                    "operation": "article_generation",
                    "model": "gpt-5.6",
                    "input_tokens": 1000,
                    "cached_input_tokens": 0,
                    "output_tokens": 500,
                    "web_search_calls": 1,
                    "estimated_cost_usd": 0.03,
                }),
                encoding="utf-8",
            )
            report = collect_report(
                start,
                end,
                root=root,
                usage_dir=usage_dir,
            )
        self.assertEqual(len(report["drafts"]), 1)
        self.assertEqual(len(report["bundles"]), 1)
        self.assertEqual(len(report["publications"]), 1)
        self.assertEqual(len(report["failures"]), 1)
        self.assertEqual(report["ai"]["estimated_cost_usd"], 0.03)
        self.assertTrue(report["asset_rank"]["in_report_window"])
        rendered_html = render_html(report)
        rendered_text = render_text(report)
        self.assertIn("https://linkedin.example/post", rendered_html)
        self.assertIn("שינוי מיקום ב-Google לפי נכס", rendered_html)
        self.assertIn("5", rendered_html)
        self.assertIn("3", rendered_html)
        self.assertIn("עלה", rendered_text)
        self.assertIn("Pinterest", rendered_text)


if __name__ == "__main__":
    unittest.main()
