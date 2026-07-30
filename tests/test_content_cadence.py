import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.reputation_core.content_cadence import (
    due_jobs,
    load_cadence,
    record_generation,
    week_key,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "content_cadence.json"


class ContentCadenceTests(unittest.TestCase):
    def setUp(self):
        self.cadence = load_cadence(CONFIG)

    def test_weekly_counts_match_approved_cadence(self):
        self.assertEqual(
            self.cadence["weekly_channel_targets"],
            {
                "facebook": 4,
                "linkedin": 4,
                "pinterest": 3,
                "instagram": 2,
                "blogger": 2,
                "google_business": 2,
            },
        )
        self.assertEqual(
            self.cadence["streams"]["canonical_depth"]["weekly_target"], 2
        )
        self.assertEqual(
            self.cadence["streams"]["health_news"]["weekly_target"], 5
        )
        self.assertEqual(
            self.cadence["streams"]["evergreen_knowledge"]["weekly_target"], 1
        )
        self.assertEqual(
            self.cadence["streams"]["media_archive"]["weekly_target"], 0
        )

    def test_sunday_plans_two_sites_but_social_only_once(self):
        sunday = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)
        jobs = due_jobs(self.cadence, {"generated": []}, sunday)
        self.assertEqual(
            [(job["stream"], job["site_key"]) for job in jobs],
            [
                ("canonical_depth", "GUYROFE_COM"),
                ("health_news", "DRGUYROFE_CO_IL"),
            ],
        )
        canonical = jobs[0]
        news = jobs[1]
        self.assertEqual(
            canonical["channels"],
            ["facebook", "linkedin", "pinterest", "google_business"],
        )
        self.assertEqual(news["channels"], [])
        self.assertFalse(canonical["public_execution_allowed"])

    def test_same_stream_is_not_generated_twice_on_same_local_day(self):
        sunday = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)
        first = due_jobs(self.cadence, {"generated": []}, sunday)[0]
        state = record_generation(
            {"generated": []},
            first,
            "content_drafts/example.md",
            sunday.isoformat(),
        )
        remaining = due_jobs(self.cadence, state, sunday)
        self.assertEqual([job["stream"] for job in remaining], ["health_news"])

    def test_tuesday_adds_only_the_distinct_wix_knowledge_stream(self):
        tuesday = datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc)
        jobs = due_jobs(self.cadence, {"generated": []}, tuesday)
        self.assertEqual(
            [(job["stream"], job["site_key"], job["channels"]) for job in jobs],
            [
                ("health_news", "DRGUYROFE_CO_IL", ["pinterest"]),
                ("evergreen_knowledge", "DRGUYROFE_COM", []),
            ],
        )
        self.assertNotIn(
            "media_archive",
            [job["stream"] for job in jobs],
        )

    def test_weekend_has_no_article_quota(self):
        friday = datetime(2026, 7, 31, 6, 0, tzinfo=timezone.utc)
        saturday = datetime(2026, 8, 1, 6, 0, tzinfo=timezone.utc)
        self.assertEqual(due_jobs(self.cadence, {"generated": []}, friday), [])
        self.assertEqual(due_jobs(self.cadence, {"generated": []}, saturday), [])

    def test_content_week_runs_sunday_through_saturday(self):
        sunday = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)
        thursday = datetime(2026, 7, 30, 6, 0, tzinfo=timezone.utc)
        self.assertEqual(week_key(sunday, self.cadence), week_key(thursday, self.cadence))

    def test_ai_images_are_forbidden(self):
        self.assertTrue(
            self.cadence["quality_policy"]["ai_image_generation_forbidden"]
        )


if __name__ == "__main__":
    unittest.main()
