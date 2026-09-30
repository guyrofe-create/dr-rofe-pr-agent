import json
import unittest

from scripts.primary_site_readonly_audit import audit_homepage
from scripts.reputation_core.asset_reinforcement import (
    approved_reinforcement_links,
    build_asset_reinforcement_plan,
)
from scripts.reputation_core.entity_graph import audit_entity_graph
from scripts.reputation_core.medical_evidence import audit_medical_claim_sources
from scripts.reputation_core.page_experience import fetch_page_experience
from scripts.reputation_core.technical_visibility import (
    audit_sitemap_membership,
    audit_structured_data,
    build_indexnow_payload,
    build_publication_lifecycle,
    normalize_provider_state,
)


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *args, **kwargs):
        return Response(self.payload)


class VisibilityExtensionTests(unittest.TestCase):
    def test_medical_claims_require_inline_sources(self):
        failed = audit_medical_claim_sources(
            "# כותרת\n\n## אבחון\n\nהבדיקה עלולה להצביע על סיכון רפואי."
            "\n\n## מקורות\nhttps://who.int/a"
        )
        self.assertFalse(failed["ready_for_medical_approval"])
        passed = audit_medical_claim_sources(
            "# כותרת\n\n## אבחון\n\nהבדיקה עלולה להצביע על סיכון רפואי לפי "
            "[הנחיות WHO](https://who.int/a)."
        )
        self.assertTrue(passed["ready_for_medical_approval"])

    def test_profile_links_and_front_matter_never_count_as_medical_evidence(self):
        report = audit_medical_claim_sources(
            "<!-- topic: בדיקה רפואית -->\n# כותרת\n"
            "מאת [ד״ר גיא רופא](https://guyrofe.com/profile/)\n\n"
            "## אבחון\n\nהבדיקה עלולה להצביע על סיכון רפואי."
        )
        self.assertFalse(report["ready_for_medical_approval"])
        self.assertEqual(report["claim_count"], 1)
        self.assertEqual(report["claim_source_matrix"][0]["source_urls"], [])

    def test_reinforcement_plan_never_injects_unproven_cross_property_homepage(self):
        plan = build_asset_reinforcement_plan(
            canonical_url="https://news.test/article/",
            canonical_name="Example Person",
            profile_url="https://main.test/profile/",
            search_target={"primary_query": "topic", "entity_queries": ["Example Person"]},
            same_site_links=[{"title": "Related", "url": "https://news.test/related/"}],
            assets=[{"url": "https://news.test/", "observed_position": 12}],
        )
        self.assertEqual(plan["complementary_owned_asset_links"], [])
        self.assertEqual(approved_reinforcement_links(plan)[0]["title"], "Related")

    def test_entity_graph_flags_shorteners_and_drift(self):
        report = audit_entity_graph(
            {"sameAs": ["https://pin.it/a"], "sites": []},
            {"owner_inventory": [{"platform": "LinkedIn", "url": "https://linkedin.com/in/a"}]},
        )
        self.assertEqual(report["status"], "review_required")
        self.assertTrue(report["short_or_redirect_urls"])

    def test_publication_lifecycle_distinguishes_accepted_from_live(self):
        self.assertTrue(normalize_provider_state({"status": "published"})["requires_reconciliation"])
        report = build_publication_lifecycle(
            url="https://example.test/a",
            receipt={"provider_state": "LIVE"},
            live_verification={"state": "verified_content"},
            sitemap_audit={"present": True},
            inspection={"verdict": "PASS", "last_crawl_time": "now"},
            search_console_row={"query": "Name", "impressions": 1},
        )
        self.assertTrue(report["complete"])

    def test_sitemap_schema_and_indexnow_are_read_only_primitives(self):
        self.assertTrue(audit_sitemap_membership(
            "https://example.test/a/", ["https://example.test/a"]
        )["present"])
        schema = audit_structured_data(
            '<script>{"@type":"Article"}{"@type":"Person"}</script>'
        )
        self.assertTrue(schema["passed"])
        payload = build_indexnow_payload(
            ["https://example.test/a"], "key", "https://example.test/key.txt"
        )
        self.assertEqual(payload["host"], "example.test")

    def test_pagespeed_adapter_preserves_field_metrics(self):
        report = fetch_page_experience("https://example.test", session=Session({
            "loadingExperience": {"metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2200, "category": "FAST"}
            }},
            "lighthouseResult": {"categories": {"performance": {"score": 0.9}}},
        }))
        self.assertEqual(report["core_web_vitals"]["lcp_ms"]["percentile"], 2200)
        self.assertFalse(report["public_write_performed"])

    def test_primary_homepage_audit_is_observational(self):
        report = audit_homepage(
            '<title>Example</title><link rel="canonical" href="https://example.test/">'
            '<h1>Example</h1><p>ספר ופודקאסט; לקביעת תור</p>',
            "https://example.test/",
            ["אינו מקבל מטופלות"],
        )
        self.assertTrue(report["signals"]["books"])
        self.assertTrue(report["signals"]["appointment_or_patient_acquisition"])
        self.assertFalse(report["public_write_performed"])


if __name__ == "__main__":
    unittest.main()
