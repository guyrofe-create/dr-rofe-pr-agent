import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_opportunities import prepare_selected_opportunities
from scripts.reputation_core.opportunity_engine import (
    ACTION_TYPES,
    build_opportunity,
    build_opportunity_portfolio,
    score_opportunity,
    select_opportunities,
)


ASSET = {
    "id": "official",
    "platform": "official",
    "url": "https://example.test",
    "tier": "A",
    "priority": 100,
    "controlled": True,
    "status": "active",
}


class OpportunityScoringTests(unittest.TestCase):
    def test_lower_burden_wins_with_equal_benefit(self):
        fast = score_opportunity(8, 9, 10, 10, 2, 1, 2)
        slow = score_opportunity(8, 9, 10, 10, 8, 6, 5)
        self.assertGreater(
            fast["opportunity_score"], slow["opportunity_score"]
        )
        self.assertIn("authority", fast["formula"])

    def test_every_requested_action_type_is_supported(self):
        built = [
            build_opportunity(
                {
                    "action_type": action_type,
                    "asset_id": "official",
                    "query": "Example",
                    "reason": action_type,
                },
                [ASSET],
                {"Example": 100},
            )
            for action_type in ACTION_TYPES
        ]
        self.assertEqual(
            {item["action_type"] for item in built},
            set(ACTION_TYPES),
        )
        self.assertTrue(all(
            item["final_execution_requires_approval"] for item in built
        ))
        self.assertTrue(all(
            item["preparation_autonomous"] for item in built
        ))

    def test_selection_enforces_capacity_risk_and_asset_concentration(self):
        actions = []
        for index in range(5):
            item = build_opportunity(
                {
                    "action_type": "strengthen_existing_asset",
                    "asset_id": "official",
                    "query": f"Example {index}",
                    "reason": f"reason {index}",
                    "risk": 2,
                },
                [ASSET],
                {},
            )
            actions.append(item)
        high_risk = build_opportunity(
            {
                "action_type": "propose_new_asset",
                "query": "Example",
                "reason": "new",
                "risk": 8,
            },
            [ASSET],
            {},
        )
        result = select_opportunities(
            actions + [high_risk],
            {
                "minimum_score": 0,
                "maximum_selected_per_cycle": 3,
                "maximum_per_asset": 1,
                "maximum_risk": 6,
            },
        )
        self.assertEqual(len(result["selected_for_preparation"]), 1)
        self.assertEqual(
            high_risk["status"], "deferred_risk_ceiling"
        )

    def test_content_freeze_allows_preparation_but_not_execution(self):
        item = build_opportunity(
            {
                "action_type": "correct_profile_or_fact",
                "asset_id": "official",
                "query": "Example",
                "reason": "incorrect fact",
            },
            [ASSET],
            {"Example": 100},
        )
        result = select_opportunities(
            [item], {"minimum_score": 0}, content_freeze=True
        )
        selected = result["selected_for_preparation"][0]
        self.assertEqual(
            selected["execution_mode"],
            "prepare_only_due_to_content_freeze",
        )
        self.assertTrue(selected["final_execution_requires_approval"])

    def test_owner_managed_asset_is_blocked(self):
        managed = {
            **ASSET,
            "id": "instagram",
            "automation": "owner_managed_product_disabled",
        }
        item = build_opportunity(
            {
                "action_type": "create_new_content",
                "asset_id": "instagram",
                "reason": "test",
            },
            [managed],
            {},
        )
        self.assertEqual(item["status"], "blocked")
        self.assertIn(
            "asset is not product-managed", item["blocked_reasons"]
        )

    def test_measurement_gaps_generate_ranked_portfolio(self):
        portfolio = build_opportunity_portfolio(
            [{
                "kind": "refresh_content",
                "asset_id": "official",
                "query": "Example",
                "reason": "stale",
            }],
            [],
            [ASSET],
            {
                "serp_surfaces": [{
                    "engine": "google",
                    "surface": "web",
                    "query": "Example",
                    "desired_count_top10": 2,
                    "negative_count_top10": 1,
                    "negative_positions": [4],
                    "features": {"images": False, "video": False},
                }],
                "ai_surfaces": [{
                    "engine": "openai",
                    "surface": "consumer",
                    "prompt": "Example",
                    "factual_accuracy_rate": 0.5,
                }],
            },
            {
                "desired_results_target": 7,
                "ai_factual_accuracy_target": 1,
            },
            {"Example": 100},
            policy={"minimum_score": 0},
        )
        kinds = {
            item["action_type"]
            for item in portfolio["ranked_opportunities"]
        }
        self.assertTrue({
            "refresh_existing_content",
            "create_new_content",
            "connect_assets",
            "create_media_or_page",
            "request_correction_or_removal",
            "earn_external_mention",
            "correct_profile_or_fact",
        }.issubset(kinds))
        self.assertIn("fixed weekdays", portfolio["calendar_rule"])


class OpportunityPreparationTests(unittest.TestCase):
    def test_preparation_is_idempotent_and_never_enables_public_action(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            state_path = root / "data" / "command_center.json"
            output = root / "opportunity_drafts"
            state_path.parent.mkdir()
            opportunity = build_opportunity(
                {
                    "action_type": "create_new_content",
                    "asset_id": "official",
                    "query": "Example",
                    "reason": "measured gap",
                    "actions": ["Prepare a sourced draft"],
                },
                [ASSET],
                {"Example": 100},
            )
            opportunity["status"] = "selected_for_preparation"
            state_path.write_text(
                json.dumps({"opportunities": [opportunity]}),
                encoding="utf-8",
            )
            first = prepare_selected_opportunities(state_path, output)
            self.assertEqual(first["prepared"], [opportunity["id"]])
            bundle = json.loads(
                (output / f"{opportunity['id']}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(bundle["public_execution_allowed"])
            self.assertEqual(bundle["status"], "awaiting_item_approval")
            second = prepare_selected_opportunities(state_path, output)
            self.assertEqual(second["prepared"], [])
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                saved["opportunities"][0]["status"],
                "prepared_awaiting_approval",
            )


if __name__ == "__main__":
    unittest.main()
