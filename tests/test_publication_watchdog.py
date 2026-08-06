import unittest
from unittest.mock import Mock

from scripts import publication_watchdog


class PublicationWatchdogTests(unittest.TestCase):
    def test_classifies_known_google_quota_failure(self):
        diagnosis = publication_watchdog.classify_failure({
            "name": "Google Business Profile",
            "detail": "429 Client Error: Too Many Requests",
        })
        self.assertEqual(diagnosis["category"], "google_business_access_or_quota")
        self.assertIn("zero request quota", diagnosis["reason"])

    def test_classifies_legacy_campaign_zero(self):
        diagnosis = publication_watchdog.classify_failure({
            "name": "Campaign", "detail": "0"
        })
        self.assertEqual(diagnosis["category"], "legacy_untyped_exception")
        self.assertIn("WordPress", diagnosis["reason"])

    def test_classifies_reconciliation_before_retry(self):
        diagnosis = publication_watchdog.classify_failure({
            "name": "Google Business Profile",
            "detail": "Target may already be published; reconcile first",
        })
        self.assertEqual(diagnosis["category"], "reconciliation_required")

    def test_live_url_verification_detects_missing_publication(self):
        response = Mock(status_code=404, url="https://example.com/missing")
        result = publication_watchdog.verify_url(
            "https://example.com/missing", "Blogger", request_get=Mock(return_value=response)
        )
        self.assertEqual(result["state"], "missing")

    def test_social_login_wall_is_inconclusive_not_false_failure(self):
        response = Mock(status_code=403, url="https://linkedin.com/post")
        result = publication_watchdog.verify_url(
            "https://linkedin.com/post", "LinkedIn", request_get=Mock(return_value=response)
        )
        self.assertEqual(result["state"], "inconclusive_login_or_rate_limit")


if __name__ == "__main__":
    unittest.main()
