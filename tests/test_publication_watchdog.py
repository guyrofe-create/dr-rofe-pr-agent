import unittest
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

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

    def test_classifies_instagram_permission_without_image_advice(self):
        diagnosis = publication_watchdog.classify_failure({
            "name": "Instagram",
            "detail": "OAuthException: Application does not have permission; code=10",
        })
        self.assertEqual(diagnosis["category"], "instagram_permission_required")
        self.assertIn("changing the image will not fix", diagnosis["action"])

    def test_classifies_google_invalid_grant_as_reauthorization(self):
        diagnosis = publication_watchdog.classify_failure({
            "name": "Blogger",
            "detail": "OAuth token refresh failed: invalid_grant: expired",
        })
        self.assertEqual(
            diagnosis["category"], "google_oauth_reauthorization_required"
        )

    def test_classifies_provider_timeout_as_transient(self):
        diagnosis = publication_watchdog.classify_failure({
            "name": "drguyrofe.com",
            "detail": "ConnectTimeout: Max retries exceeded",
        })
        self.assertEqual(
            diagnosis["category"], "transient_provider_connectivity"
        )

    def test_matches_www_asset_to_receipt_destination(self):
        bundle = {"targets": [{
            "target_id": "canonical_wix",
            "platform": "Wix",
            "asset": "www.drguyrofe.com",
        }]}
        self.assertEqual(
            publication_watchdog.match_destination_target(
                {"name": "drguyrofe.com", "status": "failed"}, bundle
            ),
            "canonical_wix",
        )

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

    def test_live_url_requires_the_approved_title_to_verify_content(self):
        response = Mock(
            status_code=200,
            url="https://example.com/post",
            text="<h1>Approved medical title</h1>",
        )
        result = publication_watchdog.verify_url(
            response.url, "Blogger", expected_title="Approved medical title",
            request_get=Mock(return_value=response),
        )
        self.assertEqual(result["state"], "verified_content")

    def test_live_url_without_content_is_not_counted_as_verified(self):
        response = Mock(status_code=200, url="https://example.com/post", text="login")
        result = publication_watchdog.verify_url(
            response.url, "Facebook", expected_title="Approved title",
            request_get=Mock(return_value=response),
        )
        self.assertEqual(result["state"], "live_url_content_unconfirmed")

    def test_matches_receipt_to_explicit_approved_target(self):
        bundle = {"targets": [{"target_id": "linkedin_member", "platform": "LinkedIn"}]}
        self.assertEqual(
            publication_watchdog.match_destination_target(
                {"name": "LinkedIn", "target_id": "linkedin_member"}, bundle
            ),
            "linkedin_member",
        )

    def test_report_fails_when_approved_target_was_not_published(self):
        now = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            campaigns = root / "content_drafts" / "campaigns"
            bundles = root / "approval_bundles"
            campaigns.mkdir(parents=True)
            bundles.mkdir()
            (bundles / "apr_test.json").write_text(json.dumps({
                "targets": [
                    {"target_id": "facebook_page", "platform": "Facebook"},
                    {"target_id": "linkedin_member", "platform": "LinkedIn"},
                ]
            }), encoding="utf-8")
            (campaigns / "cmp_test.json").write_text(json.dumps({
                "approval_id": "apr_test",
                "title": "Approved title",
                "status": "partial",
                "published_at": now.isoformat(),
                "destinations": [
                    {"name": "Facebook", "target_id": "facebook_page",
                     "status": "published", "url": "https://example.com/post"},
                    {"name": "LinkedIn", "target_id": "linkedin_member",
                     "status": "skipped_not_configured"},
                ],
            }), encoding="utf-8")
            with patch.object(publication_watchdog, "PROJECT_ROOT", root), \
                 patch.object(publication_watchdog, "CAMPAIGN_ROOT", campaigns), \
                 patch.object(publication_watchdog, "BUNDLE_ROOT", bundles), \
                 patch.object(publication_watchdog, "DRAFT_INDEX", root / "missing-drafts.json"), \
                 patch.object(publication_watchdog, "BUNDLE_INDEX", root / "missing-bundles.json"):
                response = Mock(status_code=200, url="https://example.com/post", text="Approved title")
                report = publication_watchdog.build_report(
                    30, now=now, request_get=Mock(return_value=response)
                )
        self.assertEqual(report["control_status"], "failure")
        self.assertEqual(report["totals"]["intended_targets"], 2)
        self.assertEqual(report["totals"]["content_verified"], 1)
        self.assertEqual(report["totals"]["unfulfilled_intended_targets"], 1)

    def test_report_fails_when_signed_approval_bundle_is_missing(self):
        now = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            campaigns = root / "content_drafts" / "campaigns"
            bundles = root / "approval_bundles"
            campaigns.mkdir(parents=True)
            bundles.mkdir()
            (campaigns / "cmp_test.json").write_text(json.dumps({
                "approval_id": "apr_missing",
                "title": "Approved title",
                "status": "published",
                "published_at": now.isoformat(),
                "destinations": [],
            }), encoding="utf-8")
            with patch.object(publication_watchdog, "PROJECT_ROOT", root), \
                 patch.object(publication_watchdog, "CAMPAIGN_ROOT", campaigns), \
                 patch.object(publication_watchdog, "BUNDLE_ROOT", bundles), \
                 patch.object(publication_watchdog, "DRAFT_INDEX", root / "missing-drafts.json"), \
                 patch.object(publication_watchdog, "BUNDLE_INDEX", root / "missing-bundles.json"):
                report = publication_watchdog.build_report(30, now=now)
        self.assertEqual(report["control_status"], "failure")
        self.assertEqual(report["totals"]["missing_approval_bundles"], 1)


if __name__ == "__main__":
    unittest.main()
