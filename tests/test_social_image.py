import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import social_image
from scripts.social_publishers import blogger, meta, pinterest, twitter


class SocialImageTests(unittest.TestCase):
    def test_alt_text_is_natural_and_contains_name_once(self):
        text = social_image.alt_text("ד״ר גיא רופא: מדריך חדש")
        self.assertEqual(text.count("גיא רופא"), 1)
        self.assertIn("צילום אמיתי", text)
        self.assertIn("הקשור ישירות", text)

    def test_alt_text_does_not_insert_name_when_entity_is_not_relevant(self):
        text = social_image.alt_text(
            "הסבר כללי",
            "צילום של אישה קוראת ליד חלון",
            entity_relevant=False,
        )
        self.assertNotIn("גיא רופא", text)
        self.assertIn("אישה קוראת", text)

    def test_search_planner_returns_concrete_queries(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=(
                '{"queries":["woman holding hot water bottle photograph",'
                '"heating pad on sofa photograph",'
                '"menstrual calendar home photograph"]}'
            )
        )
        queries = social_image.build_search_queries(
            client,
            "כאבי מחזור קשים",
            "מתי כאב מחזור מצריך בירור",
        )
        self.assertEqual(len(queries), 3)
        prompt = client.responses.create.call_args.kwargs["input"]
        self.assertIn("real editorial photograph", prompt)
        self.assertIn("Do not request a doctor", prompt)

    @patch("scripts.social_image.review_relevance")
    @patch("scripts.social_image.requests.get")
    @patch("scripts.social_image.search_commons")
    def test_generate_selects_existing_licensed_photo_and_never_calls_image_api(
        self, search, get, review
    ):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text='{"queries":["real menopause woman photo","second query"]}'
        )
        candidate = {
            "download_url": "https://upload.wikimedia.org/photo.jpg",
            "source_image_url": "https://upload.wikimedia.org/original.jpg",
            "source_page_url": "https://commons.wikimedia.org/wiki/File:Photo.jpg",
            "creator": "Jane Example",
            "license_name": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
            "attribution": (
                "Photo.jpg — Jane Example; CC BY-SA 4.0; Wikimedia Commons"
            ),
            "media_type": "image/jpeg",
            "extension": "jpg",
            "description": "A real photo",
        }
        search.return_value = [candidate]
        download = Mock()
        download.raise_for_status.return_value = None
        download.content = b"real-photo-bytes" * 2000
        get.return_value = download
        review.return_value = (True, "צילום של אישה יושבת ליד חלון")

        result = social_image.generate("גיל המעבר", "תסמינים", client=client)

        self.assertEqual(result.content, download.content)
        self.assertEqual(result.creator, "Jane Example")
        self.assertEqual(result.license_name, "CC BY-SA 4.0")
        self.assertIn("Wikimedia Commons", result.attribution)
        client.images.generate.assert_not_called()

    def test_commons_candidate_rejects_ai_or_illustration(self):
        page = {
            "title": "File:AI generated menopause illustration.jpg",
            "canonicalurl": "https://commons.wikimedia.org/wiki/File:Example",
            "imageinfo": [
                {
                    "mime": "image/jpeg",
                    "width": 1600,
                    "height": 1200,
                    "url": "https://upload.wikimedia.org/example.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "LicenseUrl": {
                            "value": "https://creativecommons.org/licenses/by-sa/4.0/"
                        },
                        "Artist": {"value": "Example"},
                    },
                }
            ],
        }
        self.assertIsNone(social_image._candidate_from_page(page))

    @patch("scripts.social_image.requests.post")
    @patch("scripts.social_image.requests.get")
    def test_wordpress_upload_is_idempotent(self, get, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"id": 7, "source_url": "https://guyrofe.com/image.png"}
        ]
        get.return_value = response
        url = social_image.upload_to_wordpress(
            social_image.SocialImage(b"image"),
            base_url="https://guyrofe.com",
            username="user",
            app_password="password",
            slug="approved-social",
            title="כותרת",
        )
        self.assertEqual(url, "https://guyrofe.com/image.png")
        post.assert_not_called()

    @patch.dict(
        os.environ,
        {"FACEBOOK_PAGE_ID": "123", "FACEBOOK_PAGE_TOKEN": "token"},
        clear=True,
    )
    @patch("scripts.social_publishers.meta.find_recent_facebook_duplicate")
    @patch("scripts.social_publishers.meta.requests.post")
    def test_facebook_uses_photo_endpoint_when_image_exists(
        self, post, duplicate
    ):
        duplicate.return_value = None
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": "123_456"}
        post.return_value = response

        meta.publish_facebook(
            "כותרת",
            "מידע",
            "https://guyrofe.com/article",
            "https://guyrofe.com/image.png",
            "ד״ר גיא רופא — איור מידע כללי",
        )

        self.assertTrue(post.call_args.args[0].endswith("/123/photos"))
        self.assertEqual(
            post.call_args.kwargs["data"]["url"],
            "https://guyrofe.com/image.png",
        )
        self.assertEqual(
            post.call_args.kwargs["data"]["alt_text_custom"],
            "ד״ר גיא רופא — איור מידע כללי",
        )

    @patch.dict(
        os.environ,
        {"PINTEREST_ACCESS_TOKEN": "token", "PINTEREST_BOARD_ID": "board"},
        clear=True,
    )
    @patch("scripts.social_publishers.pinterest.requests.post")
    def test_pinterest_receives_alt_text(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": "pin"}
        post.return_value = response
        pinterest.publish(
            "כותרת",
            "מידע",
            "https://guyrofe.com/article",
            "https://guyrofe.com/image.png",
            "ד״ר גיא רופא — איור מידע כללי",
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["alt_text"],
            "ד״ר גיא רופא — איור מידע כללי",
        )

    @patch.dict(
        os.environ,
        {
            "GOOGLE_OAUTH_CLIENT_ID": "client",
            "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
            "GOOGLE_OAUTH_REFRESH_TOKEN": "refresh",
            "BLOGGER_BLOG_ID": "blog",
        },
        clear=True,
    )
    @patch("scripts.social_publishers.blogger._access_token", return_value="token")
    @patch("scripts.social_publishers.blogger.requests.post")
    def test_blogger_embeds_image_with_alt_text(self, post, access_token):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"url": "https://example.blogspot.com/post"}
        post.return_value = response
        blogger.publish(
            "כותרת",
            "<p>מידע</p>",
            "https://guyrofe.com/article",
            "https://guyrofe.com/image.png",
            "ד״ר גיא רופא — איור מידע כללי",
        )
        content = post.call_args.kwargs["json"]["content"]
        self.assertIn('alt="ד״ר גיא רופא — איור מידע כללי"', content)

    def test_x_publish_is_blocked_even_when_credentials_exist(self):
        with patch.dict(
            os.environ,
            {
                "TWITTER_API_KEY": "key",
                "TWITTER_API_SECRET": "secret",
                "TWITTER_ACCESS_TOKEN": "token",
                "TWITTER_ACCESS_SECRET": "access-secret",
            },
            clear=True,
        ):
            self.assertFalse(twitter.is_configured())
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                twitter.publish("כותרת", "מידע", "https://guyrofe.com")


if __name__ == "__main__":
    unittest.main()
