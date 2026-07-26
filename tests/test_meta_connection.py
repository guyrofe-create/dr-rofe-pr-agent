import os
import unittest
from unittest.mock import Mock, patch

from scripts.social_publishers import meta


class MetaConnectionTests(unittest.TestCase):
    def test_instagram_is_permanently_disabled_for_pilot(self):
        self.assertFalse(meta.instagram_is_configured())
        with self.assertRaisesRegex(RuntimeError, "owner-managed"):
            meta.publish_instagram("title", "body", "https://example.com", "image")

    def test_text_similarity_ignores_links_and_punctuation(self):
        left = "כאבי מחזור חזקים — מידע נוסף: https://guyrofe.com"
        right = "כאבי מחזור חזקים. מידע נוסף"
        self.assertGreaterEqual(meta._text_similarity(left, right), 0.78)

    @patch.dict(
        os.environ,
        {"FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"},
        clear=True,
    )
    @patch("scripts.social_publishers.meta.requests.get")
    def test_finds_duplicate_by_canonical_url(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [
                {
                    "id": "123_456",
                    "message": "פוסט אחר",
                    "permalink_url": "https://facebook.example/post",
                    "attachments": {
                        "data": [{"unshimmed_url": "https://www.guyrofe.com/article/"}]
                    },
                }
            ]
        }
        get.return_value = response

        duplicate = meta.find_recent_facebook_duplicate(
            "תוכן חדש", "https://guyrofe.com/article"
        )

        self.assertEqual(duplicate["id"], "123_456")

    @patch.dict(
        os.environ,
        {"FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"},
        clear=True,
    )
    @patch("scripts.social_publishers.meta.requests.get")
    def test_finds_crossposted_duplicate_by_text(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [
                {
                    "id": "123_789",
                    "message": "מה חשוב לדעת על כאבי מחזור חזקים? מידע נוסף",
                }
            ]
        }
        get.return_value = response

        duplicate = meta.find_recent_facebook_duplicate(
            "מה חשוב לדעת על כאבי מחזור חזקים — מידע נוסף",
            "https://guyrofe.com",
        )

        self.assertEqual(duplicate["id"], "123_789")

    @patch.dict(
        os.environ,
        {"FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"},
        clear=True,
    )
    @patch("scripts.social_publishers.meta.requests.get")
    @patch("scripts.social_publishers.meta.requests.post")
    def test_duplicate_is_not_published(self, post, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [
                {
                    "id": "123_999",
                    "message": (
                        "כותרת\n\nתוכן\n\n"
                        "קריאה מלאה: https://guyrofe.com"
                    ),
                }
            ]
        }
        get.return_value = response

        with self.assertRaises(meta.DuplicatePostError):
            meta.publish_facebook("כותרת", "תוכן", "https://guyrofe.com")

        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
