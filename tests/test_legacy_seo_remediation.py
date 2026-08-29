import os
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

from scripts import (
    apply_legacy_seo_remediation,
    prepare_legacy_seo_remediation,
    prepare_primary_legacy_seo_remediation,
    prepare_wix_legacy_seo_remediation,
)


class LegacySeoRemediationTests(unittest.TestCase):
    def test_main_site_waf_requires_independent_browser_verification(self):
        response = Mock(status_code=403, headers={})
        session = Mock()
        session.get.return_value = response
        result = apply_legacy_seo_remediation._verify_legacy_url({
            "site_key": "GUYROFE_COM",
            "old_url": "https://guyrofe.com/pilot-old/",
            "expected_new_url": "https://guyrofe.com/clean/",
        }, session=session)
        self.assertEqual(result["mode"], "browser_verification_required")

    def test_secondary_site_does_not_treat_403_as_redirect_proof(self):
        response = Mock(status_code=403, headers={})
        session = Mock()
        session.get.return_value = response
        with self.assertRaisesRegex(RuntimeError, "did not redirect"):
            apply_legacy_seo_remediation._verify_legacy_url({
                "site_key": "DRGUYROFE_CO_IL",
                "old_url": "https://www.drguyrofe.co.il/pilot-old/",
                "expected_new_url": "https://www.drguyrofe.co.il/clean/",
            }, session=session)

    def test_primary_bundle_targets_six_selected_winners_only(self):
        bundle = prepare_primary_legacy_seo_remediation.build_primary_bundle()
        self.assertEqual(len(bundle["targets"]), 6)
        for target in bundle["targets"]:
            payload = target["payload"]
            self.assertEqual(payload["site_key"], "GUYROFE_COM")
            self.assertIn("pilot", payload["old_slug"])
            self.assertNotIn("pilot", payload["new_slug"])
            self.assertTrue(payload["selection_reason"])
            self.assertNotIn("ד״ר גיא רופא", payload["new_title"])

    def test_wix_bundle_targets_only_three_exact_custom_domain_posts(self):
        bundle = prepare_wix_legacy_seo_remediation.build_wix_bundle()
        self.assertEqual(bundle["action_type"], "legacy_wix_seo_remediation")
        self.assertEqual(len(bundle["targets"]), 3)
        for target in bundle["targets"]:
            payload = target["payload"]
            self.assertEqual(payload["site_key"], "DRGUYROFE_COM")
            self.assertIn("pilot", payload["old_slug"])
            self.assertNotIn("pilot", payload["new_slug"])
            self.assertLessEqual(len(payload["new_slug"]), 100)
            self.assertNotIn("ד״ר גיא רופא", payload["new_title"])
            self.assertTrue(payload["meta_description"].endswith((".", "?", "!")))

    def test_bundle_only_targets_unique_secondary_wordpress_news(self):
        bundle, excluded = prepare_legacy_seo_remediation.build_legacy_bundle()
        self.assertEqual(bundle["action_type"], "legacy_wordpress_seo_remediation")
        self.assertTrue(bundle["targets"])
        for target in bundle["targets"]:
            payload = target["payload"]
            self.assertEqual(payload["site_key"], "DRGUYROFE_CO_IL")
            self.assertIn("pilot", payload["old_slug"])
            self.assertNotIn("pilot", payload["new_slug"])
            self.assertNotIn("ד״ר גיא רופא", payload["new_title"])
            self.assertLessEqual(len(payload["meta_description"]), 170)
            self.assertLessEqual(len(quote(payload["new_slug"], safe="-")), 180)
        self.assertTrue(any(
            item["reason"] == "manual_consolidation_required"
            for item in excluded
        ))

    def test_apply_aborts_on_collision_and_updates_only_exact_fields(self):
        payload = {
            "site_key": "DRGUYROFE_CO_IL",
            "old_url": "https://www.drguyrofe.co.il/pilot-old/",
            "old_slug": "pilot-old",
            "expected_current_title": "כותרת | ד״ר גיא רופא",
            "new_title": "כותרת",
            "new_slug": "כותרת",
            "expected_new_url": "https://www.drguyrofe.co.il/כותרת/",
            "meta_description": "ד״ר גיא רופא: תיאור שלם.",
        }
        target = {"payload": payload}
        lookup = Mock()
        lookup.json.return_value = [{
            "id": 42,
            "title": {"raw": "כותרת | ד״ר גיא רופא"},
        }]
        lookup.raise_for_status.return_value = None
        no_collision = Mock()
        no_collision.json.return_value = []
        no_collision.raise_for_status.return_value = None
        update = Mock()
        update.json.return_value = {
            "link": "https://www.drguyrofe.co.il/כותרת/",
        }
        update.raise_for_status.return_value = None
        redirect = Mock(status_code=301, headers={
            "Location": "https://www.drguyrofe.co.il/כותרת/",
        })
        session = Mock()
        session.get.side_effect = [lookup, no_collision, redirect]
        session.post.return_value = update
        with patch.dict(os.environ, {
            "WORDPRESS_DRGUYROFE_CO_IL_USER": "user",
            "WORDPRESS_DRGUYROFE_CO_IL_API": "password",
        }, clear=False):
            result = apply_legacy_seo_remediation.apply_target(
                target, session=session
            )
        self.assertEqual(result["url"], payload["expected_new_url"])
        update_payload = session.post.call_args.kwargs["json"]
        self.assertEqual(set(update_payload), {"title", "slug", "excerpt"})
        self.assertEqual(update_payload["slug"], "כותרת")

    def test_apply_recovers_an_already_partially_updated_post(self):
        payload = {
            "site_key": "DRGUYROFE_CO_IL",
            "old_url": "https://www.drguyrofe.co.il/pilot-old/",
            "old_slug": "pilot-old",
            "expected_current_title": "כותרת ארוכה | ד״ר גיא רופא",
            "new_title": "כותרת ארוכה",
            "new_slug": "כותרת-ארוכה",
            "expected_new_url": "https://www.drguyrofe.co.il/כותרת-ארוכה/",
            "meta_description": "ד״ר גיא רופא: תיאור שלם.",
        }
        missing_old = Mock()
        missing_old.json.return_value = []
        missing_old.raise_for_status.return_value = None
        recovered = Mock()
        recovered.json.return_value = [{
            "id": 42,
            "title": {"raw": "כותרת ארוכה"},
        }]
        recovered.raise_for_status.return_value = None
        no_collision = Mock()
        no_collision.json.return_value = []
        no_collision.raise_for_status.return_value = None
        update = Mock()
        update.json.return_value = {
            "link": "https://www.drguyrofe.co.il/%D7%9B%D7%95%D7%AA%D7%A8%D7%AA-%D7%90%D7%A8%D7%95%D7%9B%D7%94/",
        }
        update.raise_for_status.return_value = None
        redirect = Mock(status_code=301, headers={
            "Location": "/%D7%9B%D7%95%D7%AA%D7%A8%D7%AA-%D7%90%D7%A8%D7%95%D7%9B%D7%94/",
        })
        session = Mock()
        session.get.side_effect = [
            missing_old, recovered, no_collision, redirect
        ]
        session.post.return_value = update
        with patch.dict(os.environ, {
            "WORDPRESS_DRGUYROFE_CO_IL_USER": "user",
            "WORDPRESS_DRGUYROFE_CO_IL_API": "password",
        }, clear=False):
            result = apply_legacy_seo_remediation.apply_target(
                {"payload": payload}, session=session
            )
        self.assertEqual(result["old_url"], payload["old_url"])
        self.assertEqual(
            session.post.call_args.kwargs["json"]["slug"],
            payload["new_slug"],
        )


if __name__ == "__main__":
    unittest.main()
