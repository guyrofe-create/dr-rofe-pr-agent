import os
import unittest
from unittest.mock import Mock, patch

from scripts.social_publishers import meta


class MetaConnectionTests(unittest.TestCase):
    def test_instagram_requires_professional_account_credentials(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(meta.instagram_is_configured())
        with self.assertRaisesRegex(RuntimeError, "not configured"):
            meta.publish_instagram("title", "body", "https://example.com", "image")

    @patch.dict(
        os.environ,
        {
            "INSTAGRAM_BUSINESS_ID": "17841400000000000",
            "FACEBOOK_PAGE_TOKEN": "token",
        },
        clear=True,
    )
    @patch("scripts.social_publishers.meta.time.sleep")
    @patch("scripts.social_publishers.meta.requests.get")
    @patch("scripts.social_publishers.meta.requests.post")
    def test_publishes_approved_instagram_image_via_container(self, post, get, _sleep):
        create = Mock()
        create.raise_for_status.return_value = None
        create.json.return_value = {"id": "container-1"}
        publish = Mock()
        publish.raise_for_status.return_value = None
        publish.json.return_value = {"id": "media-1"}
        post.side_effect = [create, publish]
        ready = Mock()
        ready.raise_for_status.return_value = None
        ready.json.return_value = {"status_code": "FINISHED"}
        permalink = Mock()
        permalink.raise_for_status.return_value = None
        permalink.json.return_value = {
            "permalink": "https://www.instagram.com/p/example/"
        }
        get.side_effect = [ready, permalink]

        result = meta.publish_instagram(
            "כותרת",
            "תקציר ייחודי",
            "https://guyrofe.com/article",
            "https://guyrofe.com/image.jpg",
        )

        self.assertEqual(result, "https://www.instagram.com/p/example/")
        self.assertEqual(
            post.call_args_list[0].kwargs["data"]["image_url"],
            "https://guyrofe.com/image.jpg",
        )
        self.assertIn(
            "https://guyrofe.com/article",
            post.call_args_list[0].kwargs["data"]["caption"],
        )

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
    def test_checks_recent_post_read_access(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"id": "123_456"}]}
        get.return_value = response

        ok, detail = meta.check_recent_posts_access()

        self.assertTrue(ok)
        self.assertIn("read access confirmed", detail)

    @patch.dict(
        os.environ,
        {"FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"},
        clear=True,
    )
    @patch("scripts.social_publishers.meta.requests.get")
    def test_reads_linked_instagram_professional_account_id(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {
            "instagram_business_account": {
                "id": "17841400000000000",
                "username": "guy_rofe_md",
            }
        }
        get.return_value = response

        account, detail = meta.get_linked_instagram_account()

        self.assertEqual(account["id"], "17841400000000000")
        self.assertEqual(account["username"], "guy_rofe_md")
        self.assertEqual(detail, "linked account found")

    @patch.dict(
        os.environ,
        {
            "INSTAGRAM_BUSINESS_ID": "17841400000000000",
            "FACEBOOK_PAGE_TOKEN": "token",
        },
        clear=True,
    )
    @patch("scripts.social_publishers.meta.requests.get")
    def test_checks_direct_instagram_professional_account_access(self, get):
        response = Mock(status_code=200)
        response.json.return_value = {
            "id": "17841400000000000",
            "username": "guy_rofe_md",
        }
        get.return_value = response

        ok, detail = meta.check_instagram_access()

        self.assertTrue(ok)
        self.assertIn("@guy_rofe_md", detail)

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
    def test_homepage_link_alone_is_not_a_duplicate(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": [
                {
                    "id": "123_456",
                    "message": "תוכן שונה לחלוטין בנושא אחר",
                    "attachments": {
                        "data": [{"unshimmed_url": "https://guyrofe.com/"}]
                    },
                }
            ]
        }
        get.return_value = response

        duplicate = meta.find_recent_facebook_duplicate(
            "מה חשוב לדעת על כאבי מחזור חזקים", "https://guyrofe.com"
        )

        self.assertIsNone(duplicate)

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
                        "מידע נוסף: https://guyrofe.com/articles/example"
                    ),
                }
            ]
        }
        get.return_value = response

        with self.assertRaises(meta.DuplicatePostError):
            meta.publish_facebook(
                "כותרת", "תוכן", "https://guyrofe.com/articles/example"
            )

        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
