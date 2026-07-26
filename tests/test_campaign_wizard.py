import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.reputation_core import campaign_wizard
from scripts.reputation_core.campaign_wizard import (
    apply_approved_campaign,
    build_campaign_draft,
    parse_plain_language_brief,
    validate_campaign_draft,
)
from scripts.reputation_core.onboarding import (
    build_installation_files,
    write_installation,
)


BRIEF = (
    "כאשר מחפשים ד״ר דוגמה / דוקטור דוגמה, אני רוצה שהמשתמש "
    "יקבל זהות מקצועית מדויקת ומקורות רשמיים, דרך הנכסים "
    "האתר הרשמי / LinkedIn / https://news.example.test, "
    "תוך איסור על המצאת עובדות / הזמנה לייעוץ."
)


class CampaignBriefParserTests(unittest.TestCase):
    def test_plain_language_contract_extracts_x_y_assets_and_z(self):
        intake = parse_plain_language_brief(BRIEF)
        self.assertEqual(intake["primary_queries"], ["ד״ר דוגמה"])
        self.assertEqual(intake["secondary_queries"], ["דוקטור דוגמה"])
        self.assertIn("זהות מקצועית מדויקת", intake["desired_outcome"])
        self.assertEqual(len(intake["requested_assets"]), 3)
        self.assertEqual(
            intake["prohibitions"],
            ["המצאת עובדות", "הזמנה לייעוץ"],
        )

    def test_incomplete_plain_language_contract_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            parse_plain_language_brief(
                "כאשר מחפשים ד״ר דוגמה אני רוצה שהמשתמש יקבל מידע"
            )


class CampaignWizardTests(unittest.TestCase):
    def spec(self):
        return {
            "client_id": "example-client",
            "display_name": "ד״ר דוגמה",
            "canonical_site": "https://example.test",
            "current_role": "מחבר",
            "primary_queries": ["ד״ר דוגמה"],
            "market": {
                "country": "IL", "language": "he",
                "devices": ["mobile", "desktop"],
            },
            "sites": [{
                "key": "canonical", "url": "https://example.test",
                "base_url": "https://example.test",
                "canonical_url": "https://example.test",
                "canonical": True, "platform": "wordpress",
                "user_env": "SITE_USER", "app_password_env": "SITE_API",
            }],
            "assets": [
                {
                    "platform": "האתר הרשמי",
                    "url": "https://example.test",
                    "type": "official_site", "tier": "A", "status": "active",
                    "controlled": True, "priority": 100,
                },
                {
                    "platform": "LinkedIn",
                    "url": "https://linkedin.com/in/example",
                    "type": "profile", "tier": "A", "status": "active",
                    "controlled": True, "priority": 90,
                },
            ],
            "maintenance_capacity_units": 3,
        }

    def installation(self, root):
        strategy = json.loads(
            Path("config/reputation_strategy.json").read_text(encoding="utf-8")
        )
        write_installation(
            root, build_installation_files(self.spec(), strategy)
        )

    def draft(self, root):
        intake = parse_plain_language_brief(BRIEF)
        return build_campaign_draft(
            intake,
            json.loads(
                (root / "config/client_profile.json").read_text(encoding="utf-8")
            ),
            json.loads(
                (root / "data/fact_registry.json").read_text(encoding="utf-8")
            ),
            json.loads(
                (root / "data/asset_registry.json").read_text(encoding="utf-8")
            ),
        )

    def test_translation_contains_all_p2_outputs(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.installation(root)
            draft = self.draft(root)
            validate_campaign_draft(draft)
            self.assertTrue(draft["queries"]["primary"])
            self.assertTrue(draft["queries"]["secondary"])
            self.assertTrue(draft["desired_knowledge"]["approved_facts"])
            self.assertIn("google", draft["targets"])
            self.assertIn("ai", draft["targets"])
            self.assertEqual(len(draft["assets"]), 3)
            self.assertTrue(draft["approval_rules"])
            self.assertTrue(draft["content_constraints"])
            self.assertEqual(len(draft["success_metrics"]), 5)
            self.assertEqual(
                draft["assets"][2]["status"],
                "pending_ownership_verification",
            )

    def test_changed_draft_invalidates_approval_id(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.installation(root)
            draft = self.draft(root)
            draft["plain_language_goal"]["desired_outcome"] = "tampered"
            with self.assertRaisesRegex(ValueError, "approval id"):
                validate_campaign_draft(draft)

    def test_wrong_approval_id_cannot_change_installation(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.installation(root)
            before = (root / "config/client_profile.json").read_text(
                encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "approval id"):
                apply_approved_campaign(root, self.draft(root), "wrong")
            self.assertEqual(
                before,
                (root / "config/client_profile.json").read_text(
                    encoding="utf-8"
                ),
            )

    def test_exact_approval_activates_runtime_campaign_without_publication(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.installation(root)
            draft = self.draft(root)
            active = apply_approved_campaign(
                root, copy.deepcopy(draft), draft["approval_id"]
            )
            profile = json.loads(
                (root / "config/client_profile.json").read_text(encoding="utf-8")
            )
            targets = json.loads(
                (root / "config/serp_targets.json").read_text(encoding="utf-8")
            )
            assets = json.loads(
                (root / "data/asset_registry.json").read_text(encoding="utf-8")
            )
            self.assertEqual(active["status"], "active_awaiting_baseline")
            self.assertEqual(
                profile["search_goal"]["secondary_queries"][0]["query"],
                "דוקטור דוגמה",
            )
            self.assertEqual(
                {item["kind"] for item in targets["queries"]},
                {"primary", "secondary"},
            )
            self.assertTrue(any(
                asset.get("url") == "https://news.example.test"
                and not asset["controlled"]
                for asset in assets["assets"]
            ))
            self.assertTrue(
                profile["approval_policy"]["public_publication_required"]
            )

    def test_failed_activation_restores_the_entire_installation(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            self.installation(root)
            watched = [
                root / "config/client_profile.json",
                root / "config/serp_targets.json",
                root / "config/reputation_strategy.json",
                root / "data/fact_registry.json",
                root / "data/asset_registry.json",
                root / "data/campaign_plan.json",
            ]
            before = {path: path.read_bytes() for path in watched}
            original_write = campaign_wizard._write_json
            calls = 0

            def fail_third_write(path, payload):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("simulated write failure")
                original_write(path, payload)

            draft = self.draft(root)
            with patch.object(
                campaign_wizard, "_write_json", side_effect=fail_third_write
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    apply_approved_campaign(
                        root, draft, draft["approval_id"]
                    )
            self.assertEqual(
                before, {path: path.read_bytes() for path in watched}
            )


if __name__ == "__main__":
    unittest.main()
