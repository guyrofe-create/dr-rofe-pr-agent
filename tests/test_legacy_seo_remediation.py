import os
import unittest
from unittest.mock import Mock, patch

from scripts import apply_legacy_seo_remediation, prepare_legacy_seo_remediation


class LegacySeoRemediationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
