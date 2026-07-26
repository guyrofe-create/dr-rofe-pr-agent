import unittest
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.reputation_core.ai_evaluator import evaluate_ai_answer
from scripts.reputation_core.asset_safety import evaluate_asset_candidate
from scripts.reputation_core.coverage_safety import evaluate_coverage_safety
from scripts.reputation_core.onboarding import (
    build_installation_files,
    validate_installation_files,
    write_installation,
)
from scripts.reputation_core.strategy import (
    client_asset_policy,
    client_search_queries,
    load_client_profile,
    load_fact_registry,
)


class SingleTenantProfileTests(unittest.TestCase):
    def test_profile_is_single_tenant_and_contains_pilot_goal(self):
        profile = load_client_profile()
        self.assertEqual(profile["deployment_mode"], "single_tenant")
        self.assertEqual(
            client_search_queries(include_variants=False),
            ["ד״ר גיא רופא", "גיא רופא"],
        )
        self.assertTrue(profile["approval_policy"]["public_publication_required"])


class FactGroundedAiTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_client_profile()
        self.registry = load_fact_registry()
        self.policy = self.profile["ai_evaluation"]

    def evaluate(self, prompt, answer, **kwargs):
        return evaluate_ai_answer(
            prompt, answer, self.registry, self.policy, **kwargs
        )

    def test_unrelated_identity_cannot_pass(self):
        result = self.evaluate(
            "מי הוא ד״ר גיא רופא?",
            "ד״ר גיא רופא הוא מורה לפיזיקה ומרצה למדעים.",
        )
        self.assertEqual(result["status"], "review")
        self.assertIn("current_role", result["missing_fact_fields"])

    def test_supported_identity_can_pass(self):
        result = self.evaluate(
            "מי הוא ד״ר גיא רופא?",
            "ד״ר גיא רופא הוא יוצר תוכן רפואי ומחבר ספרים.",
        )
        self.assertEqual(result["status"], "pass")

    def test_affirmative_practice_conflict_fails(self):
        result = self.evaluate(
            "האם ד״ר גיא רופא מקבל כיום מטופלות?",
            "כן, ניתן לקבוע תור במרפאה.",
            active_practice_claim=True,
        )
        self.assertEqual(result["status"], "fail")

    def test_unknown_book_catalog_never_passes(self):
        result = self.evaluate(
            "אילו ספרים ופודקאסטים פרסם ד״ר גיא רופא?",
            "הוא פרסם ספר בשם מומצא ופודקאסט בשם רפואה על כוס קפה.",
        )
        self.assertEqual(result["status"], "review")
        self.assertIn("book_catalog", result["unknown_relevant_fields"])


class AssetSafetyTests(unittest.TestCase):
    def healthy_assets(self):
        return [
            {
                "controlled": True,
                "status": "active",
                "maintenance_health": 0.95,
            }
            for _ in range(3)
        ]

    def candidate(self):
        return {
            "distinct_purpose_score": 92,
            "content_runway_items": 14,
            "maintenance_owner": "editor",
            "authority_path": "existing audience",
            "measurement_plan": "SERP and citations",
            "distinct_audience": True,
            "risk_signals": [],
        }

    def test_healthy_distinct_candidate_can_build(self):
        decision = evaluate_asset_candidate(
            self.candidate(),
            self.healthy_assets(),
            [],
            client_asset_policy(),
            now=datetime(2026, 7, 26, tzinfo=timezone.utc),
        )
        self.assertEqual(decision.outcome, "build")
        self.assertEqual(decision.volume_limit, 2)

    def test_doorway_signal_is_rejected(self):
        candidate = self.candidate()
        candidate["risk_signals"] = ["doorway_pattern"]
        decision = evaluate_asset_candidate(
            candidate,
            self.healthy_assets(),
            [],
            client_asset_policy(),
        )
        self.assertEqual(decision.outcome, "reject")

    def test_volume_budget_forces_incubation(self):
        decision = evaluate_asset_candidate(
            self.candidate(),
            self.healthy_assets(),
            [
                {"kind": "standalone", "created_at": "2026-07-01T00:00:00+00:00"},
                {"kind": "standalone", "created_at": "2026-07-15T00:00:00+00:00"},
            ],
            client_asset_policy(),
            now=datetime(2026, 7, 26, tzinfo=timezone.utc),
        )
        self.assertEqual(decision.outcome, "incubate")

    def test_capacity_is_installation_specific_not_a_universal_asset_count(self):
        policy = client_asset_policy()
        policy["maintenance_capacity_units"] = 3
        decision = evaluate_asset_candidate(
            self.candidate(),
            self.healthy_assets(),
            [],
            policy,
        )
        self.assertEqual(decision.outcome, "incubate")
        self.assertEqual(decision.volume_limit, 0)


class CoverageSafetyTests(unittest.TestCase):
    def test_cannibalization_stops_expansion(self):
        assets = [{
            "controlled": True, "tier": "A", "status": "active",
            "maintenance_health": 0.95, "maintenance_units": 1,
        }]
        result = evaluate_coverage_safety(
            assets,
            [{"type": "query_cannibalization"}],
            client_asset_policy(),
        )
        self.assertEqual(result["mode"], "stop")
        self.assertEqual(result["available_asset_capacity"], 4)

    def test_unknown_maintenance_health_holds_expansion(self):
        assets = [{"controlled": True, "tier": "A", "status": "active"}]
        result = evaluate_coverage_safety(assets, [], client_asset_policy())
        self.assertEqual(result["mode"], "hold")


class InstallationWizardTests(unittest.TestCase):
    def spec(self):
        return {
            "client_id": "client-one",
            "display_name": "לקוח לדוגמה",
            "name_variants": ["Sample Client"],
            "canonical_site": "https://example.test",
            "current_role": "מחבר",
            "primary_queries": ["לקוח לדוגמה"],
            "market": {"country": "IL", "language": "he", "devices": ["mobile"]},
            "sites": [{
                "key": "canonical", "url": "https://example.test",
                "canonical_url": "https://example.test", "canonical": True,
                "platform": "wordpress",
            }],
            "assets": [{
                "platform": "Site", "url": "https://example.test",
                "type": "official_site", "tier": "A", "status": "active",
                "controlled": True, "priority": 100,
            }],
            "connections": [{
                "platform": "Site",
                "required_secret_names": ["CLIENT_SITE_TOKEN"],
            }],
            "maintenance_capacity_units": 2,
        }

    def test_wizard_generates_one_isolated_client_without_secret_values(self):
        base_strategy = json.loads(
            Path("config/reputation_strategy.json").read_text(encoding="utf-8")
        )
        files = build_installation_files(self.spec(), base_strategy)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            write_installation(root, files)
            validation = validate_installation_files(root)
            manifest = json.loads(
                (root / "config/secrets_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(validation["status"], "ready")
            self.assertEqual(
                json.loads(
                    (root / "config/client_profile.json").read_text(encoding="utf-8")
                )["client_id"],
                "client-one",
            )
            connection = manifest["connections"][0]
            self.assertEqual(
                set(connection),
                {"platform", "mode", "required", "currently_present", "status"},
            )
            self.assertEqual(connection["currently_present"], [])
            self.assertFalse({"value", "token", "secret_value"} & set(connection))
            targets = json.loads(
                (root / "config/serp_targets.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(targets["version"], 3)
            self.assertEqual(
                targets["measurement_plan"]["search_engines"],
                ["google", "bing"],
            )
            self.assertTrue(
                (root / "data/bing_ai_performance.json").exists()
            )

    def test_wizard_refuses_nonempty_destination_without_force(self):
        base_strategy = json.loads(
            Path("config/reputation_strategy.json").read_text(encoding="utf-8")
        )
        files = build_installation_files(self.spec(), base_strategy)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "existing.txt").write_text("owned", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                write_installation(root, files)


if __name__ == "__main__":
    unittest.main()
