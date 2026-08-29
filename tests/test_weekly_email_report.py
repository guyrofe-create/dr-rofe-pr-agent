import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.weekly_email_report import collect_report, render_html, render_text


class WeeklyEmailReportTests(unittest.TestCase):
    def test_lists_every_registered_asset_before_first_google_baseline(self):
        start = datetime(2026, 8, 22, tzinfo=timezone.utc)
        end = datetime(2026, 8, 29, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "ai_usage_events").mkdir(parents=True)
            (root / "content_drafts" / "campaigns").mkdir(parents=True)
            (root / "approval_bundles").mkdir()
            (root / "data" / "asset_registry.json").write_text(
                json.dumps({"assets": [
                    {"platform": "Main", "url": "https://example.com/"},
                    {"platform": "Legacy", "url": "https://legacy.example/",
                     "status": "quarantined"},
                    {"platform": "Missing URL", "url": None},
                ]}),
                encoding="utf-8",
            )
            report = collect_report(start, end, root=root)
        self.assertEqual(report["asset_rank"]["asset_count"], 2)
        self.assertEqual(
            report["asset_rank"]["outcome_summary"]["tracked_assets"],
            2,
        )
        self.assertIn("Main", render_text(report))
        self.assertIn("Legacy", render_text(report))

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
                json.dumps({"snapshots": [{"orchestration": {"visibility_measurement": {
                    "asset_rank_changes": {
                        "status": "compared",
                        "previous_observed_at": "2026-07-01T04:30:00Z",
                        "current_observed_at": "2026-07-15T04:30:00Z",
                        "assets": [{"platform": "LinkedIn", "url": "https://linkedin.example/profile",
                                    "previous_position": 31,
                                    "current_position": 23, "current_result_page": 3,
                                    "change": "improved"}],
                    }
                }}}]}), encoding="utf-8",
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
            (root / "publication_receipts").mkdir()
            (root / "publication_receipts" / "execution_ledger.json").write_text(
                json.dumps({"executions": {"pub_1": {
                    "platform": "LinkedIn",
                    "status": "published",
                    "published_at": "2026-07-10T12:00:00Z",
                    "url": "https://linkedin.example/post/1",
                }}}),
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
        self.assertIn("https://linkedin.example/post", render_html(report))
        self.assertIn("Pinterest", render_text(report))
        self.assertIn("מיקום נוכחי 23", render_text(report))
        self.assertIn("פרסומים בין המדידות 1", render_text(report))
        self.assertIn("נמדד שיפור לאחר פרסום", render_text(report))
        self.assertIn("מיקום קודם</th><th>מיקום נוכחי", render_html(report))

    def test_rank_report_shows_absolute_movement_and_measured_boundary(self):
        report = {
            "start": datetime(2026, 8, 8, tzinfo=timezone.utc),
            "end": datetime(2026, 8, 15, tzinfo=timezone.utc),
            "drafts": [], "bundles": [], "campaigns": [],
            "publications": [], "failures": [],
            "ai": {
                "events": 0, "input_tokens": 0, "cached_input_tokens": 0,
                "cache_write_tokens": 0, "output_tokens": 0,
                "web_search_calls": 0, "estimated_cost_usd": 0,
                "unknown_cost_events": 0, "operations": {}, "models": {},
            },
            "asset_rank": {
                "current_observed_at": "2026-08-15T06:00:00Z",
                "assets": [
                    {
                        "platform": "LinkedIn", "url": "https://linkedin.example/profile",
                        "previous_position": 47, "previous_result_depth": 1000,
                        "current_position": 32, "current_result_page": 4,
                        "current_result_depth": 1000, "change": "improved", "delta": 15,
                    },
                    {
                        "platform": "Podcast", "url": "https://podcast.example/show",
                        "previous_position": None, "previous_result_depth": 1000,
                        "current_position": None, "current_result_page": None,
                        "current_result_depth": 1000, "change": "unchanged_not_found",
                        "delta": None,
                    },
                ],
            },
        }
        text = render_text(report)
        self.assertIn("מיקום קודם 47, מיקום נוכחי 32, שינוי עלה 15 מקומות", text)
        self.assertIn("מיקום נוכחי מעל 1000", text)
        self.assertNotIn("מיקום נוכחי לא נמצא", text)


if __name__ == "__main__":
    unittest.main()
