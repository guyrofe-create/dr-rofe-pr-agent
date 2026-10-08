import unittest

from scripts.reputation_core.asset_portfolio import (
    asset_effort_decision,
    build_asset_portfolio_plan,
)
from scripts.asset_portfolio_audit import render_markdown


class AssetPortfolioTests(unittest.TestCase):
    def test_preserves_explicit_google_business_and_homepage_decisions(self):
        registry = {"assets": [
            {
                "platform": "Google Business Profile",
                "url": "https://share.google/example",
                "type": "review_profile", "tier": "A", "priority": 100,
                "controlled": True, "status": "active",
            },
            {
                "platform": "Canonical website",
                "url": "https://guyrofe.com/",
                "type": "website", "tier": "A", "priority": 100,
                "controlled": True, "status": "active",
            },
        ]}
        reachability = {"assets": [
            {
                "platform": "Google Business Profile",
                "url": "https://share.google/example",
                "reachability": "reachable", "content_audit": "complete",
                "seo_issues": ["missing_canonical", "missing_entity_name"],
            },
            {
                "platform": "Canonical website",
                "url": "https://guyrofe.com/",
                "reachability": "access_restricted_or_anti_bot",
            },
        ]}
        plan = build_asset_portfolio_plan(registry, reachability=reachability)
        by_platform = {row["platform"]: row for row in plan["assets"]}
        self.assertEqual(
            by_platform["Google Business Profile"]["action_checklist"],
            [
                "preserve_core_profile_configuration",
                "continue_exact_approved_information_posts_media_and_contextual_links",
                "measure_search_and_maps_visibility",
            ],
        )
        self.assertEqual(
            by_platform["Canonical website"]["action_checklist"],
            ["monitor_rank_and_indexation_without_content_or_structure_changes"],
        )

    def test_scores_every_asset_and_never_authorizes_public_execution(self):
        registry = {"assets": [
            {"platform": "Core", "url": "https://example.com", "tier": "A", "priority": 100, "status": "active", "controlled": True},
            {"platform": "Mirror", "url": "https://mirror.example", "tier": "Q", "priority": 0, "status": "quarantined", "controlled": True},
        ]}
        plan = build_asset_portfolio_plan(registry, generated_at="2026-10-08T00:00:00Z")
        self.assertEqual(plan["asset_count"], 2)
        self.assertFalse(plan["credentials_included"])
        self.assertTrue(all(not row["public_execution_allowed"] for row in plan["assets"]))
        self.assertEqual(plan["effort_counts"], {"core": 1, "quarantine": 1})

    def test_existing_page_one_asset_is_defended_even_when_not_tier_a(self):
        decision = asset_effort_decision({
            "platform": "Profile", "tier": "B", "priority": 60,
            "status": "active", "controlled": True, "page_one": True,
        })
        self.assertEqual(decision["effort"], "defend")

    def test_owner_disabled_asset_is_held_not_scheduled(self):
        decision = asset_effort_decision({
            "platform": "Instagram", "tier": "A", "priority": 90,
            "status": "owner_managed_product_disabled", "controlled": True,
        })
        self.assertEqual(decision["effort"], "resolve_or_hold")

    def test_not_found_public_url_is_repaired_before_content_effort(self):
        decision = asset_effort_decision({
            "platform": "Listing", "tier": "B", "priority": 70,
            "status": "active", "controlled": True,
        }, {"reachability": "not_found", "http_status": 404})
        self.assertEqual(decision["effort"], "resolve_or_hold")
        self.assertEqual(decision["http_status"], 404)
        self.assertIn("repair_or_confirm_public_url", decision["action_checklist"])

    def test_deep_audit_turns_missing_signals_into_exact_actions(self):
        decision = asset_effort_decision({
            "platform": "Author page", "type": "book_product", "tier": "A",
            "priority": 90, "status": "active", "controlled": False,
        }, {
            "reachability": "reachable", "content_audit": "complete",
            "seo_issues": ["missing_meta_description"],
            "entity_in_title": False, "official_link_present": False,
        })
        self.assertIn("request_or_document_missing_meta_description", decision["action_checklist"])
        self.assertIn("review_entity_name_in_title", decision["action_checklist"])
        self.assertIn("measure_exact_brand_serp_and_search_console_visibility", decision["action_checklist"])
        self.assertFalse(decision["audit_complete"])

    def test_markdown_lists_every_asset_without_credentials(self):
        plan = build_asset_portfolio_plan({"assets": [{
            "platform": "Core", "url": "https://example.com", "tier": "A",
            "priority": 100, "status": "active", "controlled": True,
        }]}, generated_at="2026-10-08T00:00:00Z")
        rendered = render_markdown(plan)
        self.assertIn("Core", rendered)
        self.assertIn("https://example.com", rendered)
        self.assertNotIn("password", rendered.lower())


if __name__ == "__main__":
    unittest.main()
