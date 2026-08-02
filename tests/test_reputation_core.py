import json
import os
import tempfile
import unittest

from scripts.reputation_core import CommandCenter
from scripts.reputation_core.risk import score_event
from scripts.reputation_core.growth import build_serp_asset_gap, plan_growth_campaign
from scripts.reputation_core.orchestrator import (
    build_query_control_map,
    detect_cross_domain_risk,
    evaluate_new_asset_hypothesis,
    match_asset,
    measure_asset_rank_changes,
    orchestrate_reputation_cycle,
    propose_new_assets,
)
from scripts.reputation_core.editorial_radar import (
    build_news_analysis_brief,
    rank_news_candidates,
)
from scripts.reputation_core.search_console import (
    fetch_search_console_rows,
    refresh_google_access_token,
)
from scripts.reputation_core.tactics import ranked_tactics
from scripts.reputation_core.strategy import (
    load_fact_registry,
    load_strategy,
    validate_strategy,
)


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

    def test_repeated_ai_prompt_updates_one_event_instead_of_spamming(self):
        first = self.center.ingest_monitor_report({
            "date": "2026-07-26T10:00:00",
            "alerts": [{
                "type": "ai_identity_misinformation",
                "source": "OpenAI monitor sample",
                "prompt": "מי הוא ד״ר גיא רופא?",
                "excerpt": "תשובה שגויה ראשונה",
            }],
        })
        second = self.center.ingest_monitor_report({
            "date": "2026-07-26T12:00:00",
            "alerts": [{
                "type": "ai_identity_misinformation",
                "source": "OpenAI monitor sample",
                "prompt": "מי הוא ד״ר גיא רופא?",
                "excerpt": "תשובה שגויה מעודכנת",
            }],
        })
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(len(self.center.state["events"]), 1)
        self.assertEqual(
            self.center.state["events"][0]["text"],
            "תשובה שגויה מעודכנת",
        )
        self.assertEqual(self.center.state["events"][0]["occurrences"], 2)


class SearchConsoleAdapterTests(unittest.TestCase):
    class Response:
        def __init__(self, payload, status_code=200):
            self.payload = payload
            self.status_code = status_code

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return self.payload

    class Session:
        def __init__(self):
            self.calls = []

        def post(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if "oauth2.googleapis.com" in url:
                return SearchConsoleAdapterTests.Response({"access_token": "token"})
            return SearchConsoleAdapterTests.Response({
                "rows": [{
                    "keys": ["ד״ר גיא רופא", "https://guyrofe.com/about/"],
                    "clicks": 5,
                    "impressions": 100,
                    "ctr": 0.05,
                    "position": 6.2,
                }]
            })

    def test_refresh_and_normalize_query_page_rows(self):
        session = self.Session()
        token = refresh_google_access_token("id", "secret", "refresh", session=session)
        rows = fetch_search_console_rows(
            token, ["sc-domain:guyrofe.com"], session=session
        )
        self.assertEqual(token, "token")
        self.assertEqual(rows[0]["query"], "ד״ר גיא רופא")
        self.assertEqual(rows[0]["page"], "https://guyrofe.com/about/")
        self.assertEqual(rows[0]["position"], 6.2)
        self.assertIn("sc-domain%3Aguyrofe.com", session.calls[1][0])

    def test_inaccessible_property_is_skipped(self):
        class ForbiddenSession(self.Session):
            def post(self, url, **kwargs):
                return SearchConsoleAdapterTests.Response({}, status_code=403)

        rows = fetch_search_console_rows(
            "token", ["sc-domain:missing.example"], session=ForbiddenSession()
        )
        self.assertEqual(rows, [])


class GrowthEngineTests(unittest.TestCase):
    def test_strategy_is_loadable_and_preserves_owner_invariants(self):
        strategy = load_strategy()
        validate_strategy(strategy)
        self.assertTrue(strategy["canonical_facts"]["homepage_change_prohibited"])
        self.assertEqual(
            strategy["canonical_facts"]["practice_status"],
            "not_currently_practicing",
        )
        self.assertNotIn(
            "Instagram",
            strategy["channel_policy"]["owner_managed_product_disabled"],
        )
        self.assertIn("Instagram", strategy["channel_policy"]["product_managed"])
        self.assertIn("X", strategy["channel_policy"]["disabled"])
        self.assertEqual(strategy["ai_monitoring"]["samples_per_prompt"], 3)

    def test_approved_fact_registry_entries_have_evidence(self):
        registry = load_fact_registry()
        approved = [
            fact for fact in registry["facts"] if fact["status"] == "approved"
        ]
        self.assertTrue(approved)
        self.assertTrue(all(fact.get("evidence") for fact in approved))
        unknown_fields = {item["field"] for item in registry["unknowns"]}
        self.assertIn("book_catalog", unknown_fields)

    def test_asset_registry_contains_no_credentials_and_quarantines_mirror_network(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        serialized = json.dumps(registry).lower()
        self.assertNotIn('"password"', serialized)
        self.assertNotIn('"email"', serialized)
        mirrors = [a for a in registry["assets"] if a["type"] == "web2_site"]
        self.assertTrue(mirrors)
        self.assertTrue(all(a["tier"] == "Q" and a["automation"] == "disabled" for a in mirrors))

    def test_wikidata_is_registered_as_independent_not_owned_media(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        wikidata = next(
            item for item in registry["assets"]
            if item["platform"] == "Wikidata"
        )
        self.assertFalse(wikidata["controlled"])
        self.assertIn("requested_edit_only", wikidata["automation"])

    def test_owner_supplied_assets_are_registered_without_private_sheet_details(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        expected = {
            "Facebook", "Instagram", "LinkedIn", "X", "YouTube", "TikTok",
            "Telegram", "Pinterest", "About.me", "Blogger", "Apple Podcasts",
            "Spotify", "Flipboard", "Medium", "Quora", "SlideShare", "Tumblr",
            "Google Business Profile",
        }
        owner_platforms = {item["platform"] for item in registry["owner_inventory"]}
        registered_platforms = {item["platform"] for item in registry["assets"]}
        self.assertEqual(owner_platforms, expected)
        self.assertTrue(expected.issubset(registered_platforms))
        serialized_sources = json.dumps(registry["inventory_sources"]).lower()
        self.assertNotIn("1ilxmejzh-qzac4hixzpqf9hddhzzt8_bkc49gn4ypv0", serialized_sources)
        self.assertNotIn("docs.google.com", serialized_sources)

    def test_drguyrofe_com_is_a_tier_a_knowledge_hub(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        asset = next(a for a in registry["assets"] if a["url"] == "https://www.drguyrofe.com/")
        self.assertEqual(asset["tier"], "A")
        self.assertIn("evergreen_medical_knowledge", asset["uses"])
        self.assertEqual(asset["automation"], "wix_blog_api_after_exact_p7_approval")

    def test_secondary_wix_is_a_gated_media_archive_not_a_mirror(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        asset = next(
            a for a in registry["assets"]
            if a["url"] == "https://guyrofe.wixsite.com/homepage"
        )
        self.assertEqual(asset["tier"], "B")
        self.assertEqual(asset["status"], "connected_exact_approval_required")
        self.assertEqual(asset["automation"], "exact_p7_approval")

    def test_approved_channels_and_non_practicing_surfaces_follow_policy(self):
        with open("data/asset_registry.json", encoding="utf-8") as handle:
            registry = json.load(handle)
        assets = {item["platform"]: item for item in registry["assets"]}
        self.assertEqual(
            assets["Instagram"]["automation"],
            "meta_graph_api_after_exact_approval",
        )
        self.assertEqual(assets["YouTube"]["status"], "connected_read_only")
        self.assertIn(
            "transcript_source_only",
            assets["YouTube"]["automation"],
        )
        self.assertEqual(assets["TikTok"]["automation"], "owner_managed_product_disabled")
        self.assertIn(
            "information_only",
            assets["Google Business Profile"]["automation"],
        )
        self.assertTrue(assets["X"]["automation"].startswith("disabled_"))

    def test_secret_manifest_contains_names_not_values(self):
        with open("config/secrets_manifest.json", encoding="utf-8") as handle:
            manifest = json.load(handle)
        serialized = json.dumps(manifest).lower()
        self.assertNotIn('"password"', serialized)
        self.assertNotIn('"email"', serialized)
        primary = next(
            c for c in manifest["connections"]
            if c["platform"] == "Wix primary drguyrofe.com"
        )
        secondary = next(
            c for c in manifest["connections"]
            if c["platform"] == "Wix supporting media archive"
        )
        self.assertIn("WIX_PRIMARY_DRGUYROFE_COM_SITE_ID", primary["required"])
        self.assertIn("WIX_DRGUYROFE_COM_SITE_ID", secondary["required"])
        self.assertIn("exact_approval_required", secondary["status"])
        with open("data/business_profile.json", encoding="utf-8") as handle:
            profile = json.load(handle)
        secondary_site = next(
            site for site in profile["sites"]
            if site["key"] == "GUYROFE_WIX_MEDIA_ARCHIVE"
        )
        self.assertEqual(secondary_site["audit_status"], "passed")

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
        self.assertTrue({
            "verified_fact_registry", "profile_consistency", "entity_home",
            "brand_serp_asset", "local_prominence", "expert_answer_library",
            "digital_pr", "policy_removal",
        }.issubset(tactic_ids))
        self.assertIn("ai_citation_share", campaign["success_metrics"])
        self.assertIn("ai_explicit_mention_share", campaign["success_metrics"])

    def test_ai_misinformation_routes_to_source_first_playbook(self):
        decision = score_event({
            "source": "OpenAI monitor sample",
            "text": "שגיאת זהות",
            "metadata": {"type": "ai_identity_misinformation"},
        })
        self.assertEqual(decision.recommended_playbook, "ai_misinformation_correction")
        self.assertEqual(decision.approval, "manager")

    def test_tactics_exclude_high_risk_when_requested(self):
        self.assertTrue(all(t["risk"] <= 1 for t in ranked_tactics(max_risk=1)))

    def test_query_control_map_classifies_registered_assets(self):
        assets = [
            {"platform": "Main", "url": "https://guyrofe.com/", "controlled": True,
             "tier": "A", "status": "active"},
            {"platform": "LinkedIn", "url": "https://www.linkedin.com/in/guyrofe",
             "controlled": True, "tier": "A", "status": "active"},
        ]
        control = build_query_control_map({
            "query": "ד״ר גיא רופא",
            "results": [
                {"position": 1, "link": "https://guyrofe.com/"},
                {"position": 2, "link": "https://example.com/negative", "sentiment": "negative"},
                {"position": 3, "link": "https://www.linkedin.com/in/guyrofe"},
            ],
        }, assets)
        self.assertEqual(control["controlled_count"], 2)
        self.assertEqual(control["negative_count"], 1)
        self.assertEqual(control["controlled_positions"], [1, 3])

    def test_asset_match_does_not_confuse_another_social_profile(self):
        assets = [{
            "platform": "LinkedIn",
            "url": "https://www.linkedin.com/in/guyrofe",
        }]
        self.assertIsNone(
            match_asset("https://www.linkedin.com/in/someone-else", assets)
        )

    def test_every_asset_gets_a_google_rank_change_row(self):
        assets = [
            {"platform": "Main", "url": "https://example.com/", "tier": "A"},
            {"platform": "LinkedIn", "url": "https://linkedin.com/in/person", "tier": "A"},
            {"platform": "Instagram", "url": "https://instagram.com/person", "tier": "A"},
            {"platform": "Podcast", "url": "https://podcasts.example/show", "tier": "B"},
        ]
        previous = build_query_control_map({
            "engine": "google",
            "query": "brand",
            "device": "mobile",
            "observed_at": "2026-07-01T04:30:00Z",
            "results": [
                {"position": 5, "link": "https://example.com/"},
                {"position": 2, "link": "https://linkedin.com/in/person"},
            ],
        }, assets)
        current = build_query_control_map({
            "engine": "google",
            "query": "brand",
            "device": "mobile",
            "observed_at": "2026-07-15T04:30:00Z",
            "results": [
                {"position": 2, "link": "https://example.com/"},
                {"position": 4, "link": "https://linkedin.com/in/person"},
                {"position": 7, "link": "https://instagram.com/person"},
            ],
        }, assets)
        report = measure_asset_rank_changes(assets, [current], [previous])
        rows = {item["platform"]: item for item in report["assets"]}
        self.assertEqual(report["status"], "compared")
        self.assertEqual(report["asset_count"], 4)
        self.assertEqual(rows["Main"]["change"], "improved")
        self.assertEqual(rows["Main"]["delta"], 3)
        self.assertEqual(rows["LinkedIn"]["change"], "declined")
        self.assertEqual(rows["LinkedIn"]["delta"], -2)
        self.assertEqual(rows["Instagram"]["change"], "entered_top10")
        self.assertEqual(rows["Podcast"]["change"], "unchanged_not_in_top10")

    def test_incomplete_google_run_does_not_report_false_changes(self):
        report = measure_asset_rank_changes(
            [{"platform": "Main", "url": "https://example.com/"}],
            [{"engine": "google", "results": []}],
            complete=False,
        )
        self.assertEqual(report["status"], "not_measured")
        self.assertEqual(report["assets"], [])

    def test_orchestrator_builds_closed_loop_actions_and_ai_metrics(self):
        assets = [
            {"platform": "Main", "url": "https://guyrofe.com/", "controlled": True,
             "tier": "A", "status": "active", "priority": 100,
             "maintenance_health": 0.95, "maintenance_units": 1},
            {"platform": "News", "url": "https://drguyrofe.co.il/", "controlled": True,
             "tier": "A", "status": "audit_required", "priority": 92,
             "maintenance_health": 0.9, "maintenance_units": 1},
        ]
        cycle = orchestrate_reputation_cycle(
            assets,
            [{"query": "ד״ר גיא רופא", "results": [
                {"position": 1, "link": "https://guyrofe.com/"},
                {"position": 4, "link": "https://bad.example/story", "sentiment": "negative"},
            ]}],
            ai_snapshots=[{
                "exact_answer": "answer", "factual_errors": ["wrong"],
                "cited_sources": ["https://bad.example/story"],
            }],
            search_console_rows=[{
                "query": "ד״ר גיא רופא חדשות", "page": "https://drguyrofe.co.il/news",
                "position": 8.2, "impressions": 150,
            }],
        )
        kinds = {action["kind"] for action in cycle["next_best_actions"]}
        self.assertIn("displacement_campaign", kinds)
        self.assertIn("asset_audit", kinds)
        self.assertIn("refresh_content", kinds)
        self.assertIn("ai_visibility_correction", kinds)
        self.assertEqual(cycle["ai_visibility"]["factual_accuracy_rate"], 0.0)
        measurement = cycle["visibility_measurement"]
        self.assertEqual(measurement["version"], 4)
        self.assertEqual(
            measurement["asset_rank_changes"]["status"], "baseline"
        )
        self.assertEqual(
            measurement["serp_surfaces"][0]["negative_positions"], [4]
        )
        self.assertEqual(
            measurement["ai_surfaces"][0]["factual_accuracy_rate"], 0.0
        )
        self.assertEqual(
            measurement["bing_ai_performance"]["status"], "no_data"
        )
        self.assertTrue(cycle["new_asset_proposals"])

    def test_cross_domain_duplicate_and_cannibalization_are_blocked(self):
        risks = detect_cross_domain_risk([
            {"url": "https://guyrofe.com/a", "fingerprint": "same",
             "target_query": "topic", "intent": "guide"},
            {"url": "https://drguyrofe.co.il/a", "fingerprint": "same",
             "target_query": "topic", "intent": "guide"},
        ])
        self.assertEqual(
            {risk["type"] for risk in risks},
            {"cross_domain_duplicate", "query_cannibalization"},
        )

    def test_new_asset_creation_requires_a_measured_gap(self):
        assets = [{"platform": "Main", "type": "canonical_site",
                   "url": "https://guyrofe.com", "controlled": True,
                   "tier": "A", "status": "active"}]
        proposals = propose_new_assets(assets, [{
            "query": "ד״ר גיא רופא", "desired_count": 1, "controlled_count": 1,
        }])
        self.assertTrue(any(
            proposal["asset_kind"] == "original_research_library"
            for proposal in proposals
        ))
        self.assertTrue(all(
            proposal["status"] == "evidence_required"
            and proposal["asset_gate"]["outcome"] == "evidence_required"
            for proposal in proposals
        ))

    def test_unknown_ai_answer_is_not_counted_as_factually_accurate(self):
        from scripts.reputation_core.orchestrator import evaluate_ai_visibility

        metrics = evaluate_ai_visibility([{
            "exact_answer": "תשובה שאינה נתמכת",
            "fact_evaluation": {"status": "review"},
            "cited_sources": [],
        }], set())
        self.assertEqual(metrics["factual_accuracy_rate"], 0.0)

    def test_news_radar_prefers_popular_relevant_sourced_analysis(self):
        candidates = [
            {
                "title": "כותרת בריאותית פופולרית",
                "url": "https://news.example/story",
                "primary_source_url": "https://pubmed.example/study",
                "source_kind": "major_news",
                "attention_score": 5,
                "public_health_relevance": 5,
                "analysis_gap": 5,
                "sensationalism_risk": 2,
            },
            {
                "title": "רכילות",
                "url": "https://news.example/gossip",
                "source_kind": "other",
                "attention_score": 5,
                "public_health_relevance": 0,
                "analysis_gap": 0,
            },
        ]
        ranked = rank_news_candidates(candidates)
        self.assertEqual(len(ranked), 1)
        brief = build_news_analysis_brief(ranked[0])
        self.assertEqual(brief["analyzed_news_url"], "https://news.example/story")
        self.assertIn("מה חסר או דורש הסתייגות", brief["required_sections"])

    def test_new_asset_gate_can_reject_a_creative_but_thin_idea(self):
        rejected = evaluate_new_asset_hypothesis({
            "name": "Daily cloned news domain",
            "distinct_audience": False,
            "distinct_search_intent": False,
            "original_content_inventory": False,
            "maintenance_capacity_12m": True,
            "brand_relevance": True,
            "technical_ownership": True,
            "realistic_authority_path": False,
            "duplicate_content_risk": True,
            "ymyl_review_gap": True,
            "reputation_only_purpose": True,
        })
        self.assertEqual(rejected["decision"], "reject")
        approved = evaluate_new_asset_hypothesis({
            "name": "Evidence newsroom",
            "distinct_audience": True,
            "distinct_search_intent": True,
            "original_content_inventory": True,
            "maintenance_capacity_12m": True,
            "brand_relevance": True,
            "technical_ownership": True,
            "realistic_authority_path": True,
        })
        self.assertEqual(approved["decision"], "build")


if __name__ == "__main__":
    unittest.main()
