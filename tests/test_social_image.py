import base64
import json
import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from scripts import social_image
from scripts.social_publishers import blogger, meta, pinterest, twitter


class SocialImageTests(unittest.TestCase):
    def test_alt_text_is_natural_and_contains_name_once(self):
        text = social_image.alt_text("ד״ר גיא רופא: מדריך חדש")
        self.assertEqual(text.count("גיא רופא"), 1)
        self.assertIn("מלווה מאמר", text)
        self.assertIn("מדריך חדש", text)

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
        self.assertIn("doctor treating a patient", prompt)
        self.assertIn("exposed body", prompt)
        self.assertIn("brand, logo", prompt)
        self.assertIn("evaluating online information", prompt)
        self.assertIn("2-4 concrete searchable words", prompt)

    def test_long_planner_phrases_are_compacted_for_commons(self):
        queries = social_image.expand_search_queries(
            [
                "adult comparing health information on laptop and reference books",
                "adult researching health information on tablet in library",
            ]
        )
        self.assertEqual(queries[0], "adult health laptop books")
        self.assertEqual(queries[1], "adult health tablet library")
        self.assertIn(
            "adult comparing health information on laptop and reference books",
            queries,
        )

    @patch("scripts.social_image.search_commons", return_value=[])
    def test_generate_reports_search_diagnostics_when_no_photo_is_found(self, search):
        planned = [
            "adult comparing health information laptop",
            "person reading medical reference book",
            "library health research",
            "tablet health information research",
            "adult studying reference sources",
        ]
        expected_searches = len(social_image.expand_search_queries(planned))
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=json.dumps({"queries": planned})
        )

        with self.assertRaisesRegex(
            social_image.PhotoSelectionError,
            rf"queries={expected_searches}.*unique_candidates=0.*reviewed=0",
        ):
            social_image.select_licensed_photo(
                "איך להעריך מידע רפואי ברשת",
                "זיהוי מקורות אמינים והשוואת מידע",
                client=client,
            )

        self.assertEqual(search.call_count, expected_searches)

    def test_commons_selector_reports_planner_failure(self):
        client = Mock()
        client.responses.create.side_effect = TimeoutError("planner unavailable")

        with self.assertRaisesRegex(
            social_image.PhotoSelectionError,
            "planner=TimeoutError",
        ):
            social_image.select_licensed_photo("כותרת", "תקציר", client=client)

    @patch("scripts.social_image.review_relevance")
    @patch("scripts.social_image.requests.get")
    @patch("scripts.social_image.search_commons")
    def test_commons_selector_can_still_select_a_licensed_photo(
        self, search, get, review
    ):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text=(
                '{"queries":["real menopause woman photo","second query",'
                '"third query"]}'
            )
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

        result = social_image.select_licensed_photo(
            "גיל המעבר", "תסמינים", client=client
        )

        self.assertEqual(result.content, download.content)
        self.assertEqual(result.creator, "Jane Example")
        self.assertEqual(result.license_name, "CC BY-SA 4.0")
        self.assertIn("Wikimedia Commons", result.attribution)
        self.assertEqual(
            result.source_type, "wikimedia_commons_licensed_photo"
        )
        client.images.generate.assert_not_called()

    @patch(
        "scripts.social_image.select_licensed_photo",
        side_effect=social_image.PhotoSelectionError("none"),
    )
    def test_generate_uses_gpt_image_and_builds_four_text_free_variants(self, select):
        source = BytesIO()
        Image.new("RGB", (1536, 1024), "#4f7f87").save(source, format="PNG")
        client = Mock()
        client.images.generate.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(source.getvalue()).decode("ascii")
                )
            ]
        )
        client.responses.create.return_value = SimpleNamespace(
            output_text="ACCEPT: צילום של מחשב נייד, זכוכית מגדלת וספרי רפואה"
        )

        result = social_image.generate(
            "איך להעריך מידע רפואי ברשת | ד״ר גיא רופא",
            "זיהוי מקורות אמינים",
            client=client,
        )

        self.assertEqual(result.source_type, "openai_generated_text_free_visual")
        self.assertEqual(
            set(result.variants),
            {"hero", "landscape", "square", "portrait"},
        )
        self.assertEqual(Image.open(BytesIO(result.variants["hero"])).size, (1600, 900))
        self.assertEqual(
            Image.open(BytesIO(result.variants["landscape"])).size,
            (1200, 630),
        )
        self.assertEqual(
            Image.open(BytesIO(result.variants["portrait"])).size,
            (1080, 1350),
        )
        call = client.images.generate.call_args.kwargs
        self.assertEqual(call["model"], "gpt-image-2")
        self.assertIn("Do not add any letters", call["prompt"])
        self.assertIn("laptop, magnifying glass", call["prompt"])
        select.assert_called_once()

    @patch("scripts.social_image.select_licensed_photo")
    def test_generate_prefers_licensed_photo_and_preserves_provenance(self, select):
        source = BytesIO()
        Image.new("RGB", (1600, 1200), "#64858a").save(source, format="JPEG")
        select.return_value = social_image.SocialImage(
            content=source.getvalue(),
            media_type="image/jpeg",
            extension="jpg",
            visual_description="צילום של ספר רפואי פתוח",
            source_page_url="https://commons.wikimedia.org/wiki/File:Medical.jpg",
            creator="Jane Example",
            license_name="CC BY 4.0",
            license_url="https://creativecommons.org/licenses/by/4.0/",
            attribution="Jane Example, CC BY 4.0",
            source_type="wikimedia_commons_licensed_photo",
        )
        client = Mock()

        result = social_image.generate("כותרת", "תקציר", client=client)

        self.assertEqual(result.source_type, "wikimedia_commons_licensed_photo")
        self.assertEqual(result.creator, "Jane Example")
        self.assertEqual(result.license_name, "CC BY 4.0")
        self.assertEqual(set(result.variants), {"hero", "landscape", "square", "portrait"})
        client.images.generate.assert_not_called()

    @patch(
        "scripts.social_image.select_licensed_photo",
        side_effect=social_image.PhotoSelectionError("none"),
    )
    def test_generate_fails_closed_when_image_api_is_unavailable(self, select):
        client = Mock()
        client.images.generate.side_effect = TimeoutError("image API unavailable")

        with self.assertRaisesRegex(
            RuntimeError, "No generated image passed strict"
        ):
            social_image.generate("כותרת", "תקציר", client=client)
        self.assertEqual(
            client.images.generate.call_count, social_image.MAX_GENERATION_ATTEMPTS
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_generate_fails_closed_when_openai_key_is_missing(self):
        with self.assertRaisesRegex(RuntimeError, "OpenAI image client is unavailable"):
            social_image.generate("כותרת", "תקציר")

    @patch(
        "scripts.social_image.select_licensed_photo",
        side_effect=RuntimeError("unexpected Commons failure"),
    )
    def test_unexpected_photo_search_failure_still_uses_reviewed_generation(self, select):
        client = Mock()
        source = BytesIO()
        Image.new("RGB", (1536, 1024), "#4f7f87").save(source, format="PNG")
        client.images.generate.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(source.getvalue()).decode("ascii")
                )
            ]
        )
        client.responses.create.return_value = SimpleNamespace(
            output_text="ACCEPT: צילום של ציוד רפואי רלוונטי ללא מלל"
        )
        result = social_image.generate("כותרת", "תקציר", client=client)

        self.assertEqual(result.source_type, "openai_generated_text_free_visual")
        self.assertGreater(len(result.content), 2_000)

    @patch(
        "scripts.social_image.select_licensed_photo",
        side_effect=social_image.PhotoSelectionError("none"),
    )
    def test_rejected_generated_image_is_retried_with_feedback(self, select):
        source = BytesIO()
        Image.new("RGB", (1536, 1024), "#4f7f87").save(source, format="PNG")
        client = Mock()
        client.images.generate.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(source.getvalue()).decode("ascii")
                )
            ]
        )
        client.responses.create.side_effect = [
            SimpleNamespace(output_text="REJECT: visible text on monitor"),
            SimpleNamespace(output_text="ACCEPT: צילום של ציוד אולטרסאונד ללא מלל"),
        ]

        result = social_image.generate(
            "מיומות ברחם | ד״ר גיא רופא", "בירור באמצעות אולטרסאונד", client=client
        )

        self.assertEqual(client.images.generate.call_count, 2)
        second_prompt = client.images.generate.call_args.kwargs["prompt"]
        self.assertIn("visible text on monitor", second_prompt)
        self.assertIn("absolutely no fetus", second_prompt)
        self.assertIn("ציוד אולטרסאונד", result.visual_description)

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
