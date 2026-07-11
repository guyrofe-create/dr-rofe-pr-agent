import json
import os
import tempfile
import unittest

from scripts.reputation_core import CommandCenter
from scripts.reputation_core.risk import score_event
from scripts.reputation_core.growth import build_serp_asset_gap, plan_growth_campaign
from scripts.reputation_core.tactics import ranked_tactics


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


class GrowthEngineTests(unittest.TestCase):
    def test_asset_registry_contains_no_credentials_and_quarantines_mirror_network(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        serialized = json.dumps(registry).lower()
        self.assertNotIn('"password"', serialized)
        self.assertNotIn('"email"', serialized)
        mirrors = [a for a in registry["assets"] if a["type"] == "web2_site"]
        self.assertTrue(mirrors)
        self.assertTrue(all(a["tier"] == "Q" and a["automation"] == "disabled" for a in mirrors))

    def test_drguyrofe_com_is_a_tier_a_knowledge_hub(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        asset = next(a for a in registry["assets"] if a["url"] == "https://www.drguyrofe.com/")
        self.assertEqual(asset["tier"], "A")
        self.assertIn("knowledge_hub", asset["uses"])
        self.assertEqual(asset["automation"], "wix_api_after_site_id")

    def test_secret_manifest_contains_names_not_values(self):
        with open("config/secrets_manifest.json", encoding="utf-8") as handle:
            manifest = json.load(handle)
        serialized = json.dumps(manifest).lower()
        self.assertNotIn('"password"', serialized)
        self.assertNotIn('"email"', serialized)
        wix = next(c for c in manifest["connections"] if c["platform"] == "Wix drguyrofe.com")
        self.assertIn("WIX_DRGUYROFE_COM_SITE_ID", wix["required"])
        self.assertEqual(wix["status"], "missing_site_id")

    def test_asset_gap_distinguishes_controlled_and_independent(self):
        gap = build_serp_asset_gap([
            {"type": "canonical_site", "controlled": True, "page_one": True},
            {"type": "independent_media", "controlled": False, "page_one": True},
        ], target_slots=5)
        self.assertEqual(gap["slot_gap"], 3)
        self.assertEqual(gap["controlled_page_one_assets"], 1)
        self.assertEqual(gap["independent_page_one_assets"], 1)

    def test_campaign_routes_visibility_gaps_to_multiple_surfaces(self):
        campaign = plan_growth_campaign({"name": "Example"}, {
            "serp_assets": [], "canonical_entity_complete": False,
            "local_rank_weak": True, "ai_citation_gap": True,
            "ai_mention_gap": True, "independent_authority_gap": True,
            "eligible_policy_violations": 1,
        })
        tactic_ids = {task["tactic"] for task in campaign["tasks"]}
        self.assertTrue({"entity_home", "brand_serp_asset", "local_prominence", "expert_answer_library", "digital_pr", "policy_removal"}.issubset(tactic_ids))
        self.assertIn("ai_citation_share", campaign["success_metrics"])
        self.assertIn("ai_explicit_mention_share", campaign["success_metrics"])

    def test_tactics_exclude_high_risk_when_requested(self):
        self.assertTrue(all(t["risk"] <= 1 for t in ranked_tactics(max_risk=1)))


if __name__ == "__main__":
    unittest.main()
