import json
import os
import tempfile
import unittest

from scripts.reputation_core import CommandCenter
from scripts.reputation_core.risk import score_event


class RiskScoringTests(unittest.TestCase):
    def test_positive_review_is_low_priority(self):
        decision = score_event({"source": "google", "rating": 5, "text": "שירות מצוין"})
        self.assertEqual(decision.priority, "P4")
        self.assertEqual(decision.category, "positive_review")

    def test_one_star_harassment_routes_to_policy_playbook(self):
        decision = score_event({"source": "Google Business", "rating": 1, "text": "מחכים לך בכלא ובתא"})
        self.assertGreaterEqual(decision.score, 35)
        self.assertEqual(decision.category, "harassment")
        self.assertEqual(decision.recommended_playbook, "policy_violation")

    def test_fast_high_reach_legal_event_is_crisis(self):
        decision = score_event({
            "source": "news", "text": "חקירה ותביעה בעקבות סכנה", "estimated_reach": 250000, "velocity": 12,
        })
        self.assertEqual(decision.priority, "P0")
        self.assertEqual(decision.approval, "executive_legal")


class CommandCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.temp.name, "state.json")
        self.center = CommandCenter(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_ingest_is_idempotent(self):
        raw = {"source": "web", "url": "https://example.com/a", "title": "Mention", "text": "neutral"}
        first, first_created = self.center.ingest(raw)
        second, second_created = self.center.ingest(raw)
        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["occurrences"], 2)
        self.assertEqual(len(self.center.state["events"]), 1)

    def test_crisis_opens_room_and_freezes_content(self):
        event, _ = self.center.ingest({
            "source": "news", "title": "Breaking", "text": "חקירה סכנה תביעה",
            "estimated_reach": 100000, "velocity": 20,
        })
        self.assertEqual(event["priority"], "P0")
        self.assertTrue(self.center.state["content_freeze"])
        self.assertEqual(len(self.center.state["crisis_rooms"]), 1)
        self.assertGreater(len(self.center.state["tasks"]), 0)

    def test_monitor_report_routes_alerts_and_mentions(self):
        created = self.center.ingest_monitor_report({
            "date": "2026-07-11T10:00:00",
            "alerts": [{"type": "negative_review", "source": "Google Business", "rating": 1, "author": "A", "excerpt": "שירות גרוע"}],
            "web_mentions": {"new_mentions": [{"title": "New profile", "link": "https://example.com/profile"}]},
        })
        self.assertEqual(len(created), 2)
        self.center.save()
        with open(self.path, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(saved["metrics"]["open_events"], 2)


if __name__ == "__main__":
    unittest.main()
