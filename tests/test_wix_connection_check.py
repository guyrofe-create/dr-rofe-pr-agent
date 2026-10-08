import unittest
from unittest.mock import patch

from scripts import wix_connection_check


class WixConnectionCheckTests(unittest.TestCase):
    @patch.object(wix_connection_check, "check", return_value=True)
    def test_read_only_mode_does_not_require_blog_author(self, _check):
        with patch.object(wix_connection_check, "API_KEY", "key"), patch.object(
            wix_connection_check, "SITE_ID", "site"
        ), patch.object(wix_connection_check, "ACCOUNT_ID", ""):
            self.assertEqual(wix_connection_check.main(["--read-only"]), 0)


if __name__ == "__main__":
    unittest.main()
