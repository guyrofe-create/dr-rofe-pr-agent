import os
import unittest
from unittest.mock import Mock

from scripts.social_publishers import google_oauth


class GoogleOAuthTests(unittest.TestCase):
    def test_invalid_grant_preserves_actionable_provider_detail(self):
        response = Mock()
        response.ok = False
        response.status_code = 400
        response.json.return_value = {
            "error": "invalid_grant",
            "error_description": "Token has been expired or revoked.",
        }
        session = Mock()
        session.post.return_value = response
        with unittest.mock.patch.dict(
            os.environ,
            {
                "GOOGLE_OAUTH_CLIENT_ID": "client",
                "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
                "GOOGLE_OAUTH_REFRESH_TOKEN": "refresh",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(
                google_oauth.GoogleOAuthError,
                "invalid_grant.*expired or revoked",
            ):
                google_oauth.refresh_access_token(session=session)

    def test_missing_shared_credentials_are_named_without_network_call(self):
        session = Mock()
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                google_oauth.GoogleOAuthError,
                "GOOGLE_OAUTH_CLIENT_ID.*GOOGLE_OAUTH_REFRESH_TOKEN",
            ):
                google_oauth.refresh_access_token(session=session)
        session.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
