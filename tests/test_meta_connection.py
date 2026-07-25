import os
import unittest
from unittest.mock import Mock, patch

from scripts.social_publishers import meta


class MetaConnectionTests(unittest.TestCase):
    @patch.dict(os.environ, {"INSTAGRAM_BUSINESS_ID": "178400000000001"}, clear=True)
    def test_uses_explicit_instagram_id(self):
        self.assertEqual(meta.resolve_instagram_business_id(), "178400000000001")

    @patch.dict(os.environ, {
        "FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"
    }, clear=True)
    @patch("scripts.social_publishers.meta.requests.get")
    def test_discovers_instagram_id_from_page(self, get):
        response = Mock()
        response.json.return_value = {
            "instagram_business_account": {"id": "178400000000002", "username": "example"}
        }
        response.raise_for_status.return_value = None
        get.return_value = response
        self.assertEqual(meta.resolve_instagram_business_id(), "178400000000002")

    @patch.dict(os.environ, {
        "FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"
    }, clear=True)
    @patch("scripts.social_publishers.meta.requests.get")
    def test_discovers_connected_creator_account(self, get):
        response = Mock()
        response.json.return_value = {
            "connected_instagram_account": {"id": "178400000000003", "username": "creator"}
        }
        response.raise_for_status.return_value = None
        get.return_value = response
        self.assertEqual(meta.resolve_instagram_business_id(), "178400000000003")

    @patch.dict(os.environ, {
        "INSTAGRAM_BUSINESS_ID": "178400000000004",
        "FACEBOOK_PAGE_TOKEN": "token",
    }, clear=True)
    @patch("scripts.social_publishers.meta.requests.get")
    def test_checks_direct_instagram_account_access(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": "178400000000004",
            "username": "guy_rofe_md",
        }
        get.return_value = response
        self.assertEqual(
            meta.check_instagram_account_access(),
            (True, "guy_rofe_md"),
        )

    @patch.dict(os.environ, {
        "INSTAGRAM_BUSINESS_ID": "178400000000005",
        "FACEBOOK_PAGE_TOKEN": "token",
    }, clear=True)
    @patch("scripts.social_publishers.meta.requests.get")
    def test_reports_instagram_token_permission_failure(self, get):
        response = Mock(status_code=403, text="permission denied")
        get.return_value = response
        ok, detail = meta.check_instagram_account_access()
        self.assertFalse(ok)
        self.assertIn("HTTP 403", detail)


if __name__ == "__main__":
    unittest.main()
