import unittest

from scripts.reputation_core.creative_asset_engine import (
    ASSET_ARCHETYPES,
    MANDATORY_PROOFS,
    build_creative_asset_portfolio,
    candidate_to_action,
    evaluate_creative_asset_candidate,
)
from scripts.reputation_core.opportunity_engine import build_opportunity
from scripts.reputation_core.strategy import client_asset_policy


HEALTHY_ASSETS = [{
    "id": "official",
    "type": "canonical_site",
    "controlled": True,
    "tier": "A",
    "status": "active",
    "maintenance_health": 0.95,
    "maintenance_units": 1,
}]


def full_evidence(item_count=12, **extra):
    return {
        "purpose_verified": True,
        "purpose_statement": "A distinct useful product for a real audience.",
        "distinct_audience": "People seeking structured evidence",
        "distinct_intent": "Research retrieval rather than identity lookup",
        "reader_value_verified": True,
        "reader_value_statement": "Original reviewed evidence and utilities.",
        "original_content_plan": [
            f"Original item {index}" for index in range(item_count)
        ],
        "maintenance_owner": "editor",
        "maintenance_schedule": "monthly audit and quarterly refresh",
        "maintenance_months": 12,
        "capacity_verified": True,
        "authority_path": "authoritative platform and relevant citations",
        "query_surface_fit": "the surface directly serves the observed intent",
        "index_or_discovery_path": "public indexable URLs and sitemap",
        "measurement_plan": "query, index and citation checks",
        "duplication_review_completed": True,
        "doorway_review_completed": True,
        "maximum_content_similarity": 0.2,
        "distinct_purpose_score": 95,
        **extra,
    }


class CreativeAssetPortfolioTests(unittest.TestCase):
    def policy(self):
        policy = client_asset_policy()
        policy["desired_results_target"] = 7
        return policy

    def gap(self):
        return [{
            "query": "Example",
            "desired_count": 2,
            "controlled_count": 1,
        }]

    def test_six_requested_asset_archetypes_exist(self):
        self.assertEqual(len(ASSET_ARCHETYPES), 6)
        self.assertEqual(
            set(ASSET_ARCHETYPES),
            {
                "authoritative_profile",
                "youtube_or_video_series",
                "knowledge_library_or_hub",
                "books_apps_research_projects_page",
                "standalone_system_asset",
                "earned_article_interview_or_research",
            },
        )

    def test_measured_gap_generates_candidates_but_not_build_permission(self):
        portfolio = build_creative_asset_portfolio(
            HEALTHY_ASSETS, self.gap(), [], [], self.policy()
        )
        self.assertEqual(portfolio["measured_gap"], 5)
        self.assertEqual(len(portfolio["candidates"]), 6)
        self.assertEqual(
            set(portfolio["mandatory_proofs"]),
            set(MANDATORY_PROOFS),
        )
        self.assertTrue(all(
            item["gate"]["outcome"] == "evidence_required"
            for item in portfolio["candidates"]
        ))
        self.assertTrue(all(
            not item["gate"]["all_mandatory_proofs_pass"]
            for item in portfolio["candidates"]
        ))

    def test_no_measured_gap_means_no_asset_candidates(self):
        portfolio = build_creative_asset_portfolio(
            HEALTHY_ASSETS,
            [{"query": "Example", "desired_count": 7, "controlled_count": 5}],
            [],
            [],
            self.policy(),
        )
        self.assertEqual(portfolio["candidates"], [])

    def test_existing_profile_and_video_are_not_reproposed(self):
        assets = HEALTHY_ASSETS + [
            {"type": "professional_profile", "status": "active"},
            {"type": "video_channel", "status": "active"},
        ]
        portfolio = build_creative_asset_portfolio(
            assets, self.gap(), [], [], self.policy()
        )
        archetypes = {
            item["archetype"] for item in portfolio["candidates"]
        }
        self.assertNotIn("authoritative_profile", archetypes)
        self.assertNotIn("youtube_or_video_series", archetypes)

    def test_duplicate_inventory_hard_stops_every_new_candidate(self):
        inventory = [
            {
                "url": "https://one.test/a",
                "fingerprint": "same",
                "target_query": "same intent",
            },
            {
                "url": "https://two.test/a",
                "fingerprint": "same",
                "target_query": "same intent",
            },
        ]
        portfolio = build_creative_asset_portfolio(
            HEALTHY_ASSETS,
            self.gap(),
            inventory,
            [],
            self.policy(),
        )
        self.assertTrue(all(
            item["gate"]["outcome"] == "reject"
            for item in portfolio["candidates"]
        ))


class CreativeAssetProofTests(unittest.TestCase):
    def candidate(self, archetype="knowledge_library_or_hub", evidence=None):
        source = ASSET_ARCHETYPES[archetype]
        return {
            "archetype": archetype,
            "minimum_original_items": source["minimum_original_items"],
            "standalone": bool(source.get("standalone")),
            "earned": bool(source.get("earned")),
            "proof_evidence": evidence or {},
            "risk_signals": (evidence or {}).get("risk_signals", []),
        }

    def test_all_five_proofs_and_capacity_are_required_for_build(self):
        decision = evaluate_creative_asset_candidate(
            self.candidate(evidence=full_evidence()),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertTrue(decision["all_mandatory_proofs_pass"])
        self.assertEqual(
            {proof["status"] for proof in decision["proofs"].values()},
            {"pass"},
        )
        self.assertEqual(decision["outcome"], "build")

    def test_missing_any_mandatory_proof_prevents_build(self):
        evidence = full_evidence()
        evidence.pop("maintenance_owner")
        decision = evaluate_creative_asset_candidate(
            self.candidate(evidence=evidence),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertEqual(decision["outcome"], "evidence_required")
        self.assertIn(
            "sustainable_maintenance", decision["missing_proofs"]
        )

    def test_standalone_site_has_two_additional_systemic_purpose_proofs(self):
        decision = evaluate_creative_asset_candidate(
            self.candidate(
                "standalone_system_asset",
                full_evidence(),
            ),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertEqual(decision["outcome"], "evidence_required")
        purpose = decision["proofs"]["separate_system_purpose"]
        self.assertIn(
            "proof the asset remains valuable without reputation benefit",
            purpose["missing"],
        )
        passed = evaluate_creative_asset_candidate(
            self.candidate(
                "standalone_system_asset",
                full_evidence(
                    valuable_without_reputation_benefit=True,
                    cannot_fit_existing_asset=True,
                ),
            ),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertTrue(passed["all_mandatory_proofs_pass"])

    def test_doorway_or_fake_independence_is_rejected(self):
        evidence = full_evidence(
            risk_signals=["doorway_pattern", "fake_independence"]
        )
        decision = evaluate_creative_asset_candidate(
            self.candidate(evidence=evidence),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertEqual(decision["outcome"], "reject")
        self.assertEqual(
            decision["failed_proofs"],
            ["no_duplication_or_doorway"],
        )

    def test_earned_placement_requires_verified_editorial_independence(self):
        decision = evaluate_creative_asset_candidate(
            self.candidate(
                "earned_article_interview_or_research",
                full_evidence(item_count=1),
            ),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertEqual(decision["outcome"], "evidence_required")
        passed = evaluate_creative_asset_candidate(
            self.candidate(
                "earned_article_interview_or_research",
                full_evidence(
                    item_count=1,
                    editorial_independence_verified=True,
                ),
            ),
            HEALTHY_ASSETS,
            [],
            client_asset_policy(),
        )
        self.assertEqual(passed["outcome"], "build")

    def test_p5_candidate_converts_to_approval_only_p4_action(self):
        archetype = ASSET_ARCHETYPES["standalone_system_asset"]
        candidate = {
            "archetype": "standalone_system_asset",
            "asset_kind": archetype["legacy_kind"],
            "asset_type": archetype["asset_type"],
            "delivery_mode": archetype["delivery_mode"],
            "query": "Example",
            "measured_gap": 5,
            "surface": archetype["surfaces"],
            "reader_value_hypothesis": archetype["reader_value"],
            "impact": archetype["impact"],
            "authority": archetype["authority"],
            "speed": archetype["speed"],
            "creative_priority_score": 50,
            "gate": {
                "outcome": "evidence_required",
                "missing_proofs": list(MANDATORY_PROOFS),
                "failed_proofs": [],
            },
        }
        action = candidate_to_action(candidate)
        self.assertEqual(action["action_type"], "propose_new_asset")
        self.assertEqual(action["approval_required"], "owner")
        self.assertEqual(action["status"], "evidence_required")
        self.assertEqual(action["source_kind"], "p5_creative_asset_engine")
        opportunity = build_opportunity(action, HEALTHY_ASSETS, {"Example": 100})
        self.assertEqual(
            opportunity["authorization_scope"],
            "proof_collection_only",
        )
        self.assertFalse(opportunity["new_asset_build_authorized"])
        self.assertEqual(
            len([
                item for item in opportunity["approval_bundle_requirements"]
                if item.startswith("Proof ")
            ]),
            5,
        )


if __name__ == "__main__":
    unittest.main()
