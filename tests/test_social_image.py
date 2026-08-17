import json
import os
import unittest
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from PIL import Image

from scripts import social_image
from scripts.social_publishers import blogger, meta, pinterest, twitter


class SocialImageTests(unittest.TestCase):
    def test_review_verdict_accepts_common_safe_separators(self):
        self.assertEqual(
            social_image._parse_review_verdict(
                "**ACCEPT** — צילום של ציוד רפואי ללא מלל"
            ),
            ("ACCEPT", "צילום של ציוד רפואי ללא מלל"),
        )

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
        self.assertIn("only for direct topical relevance", prompt)
        self.assertIn("visible text, labels and brands are all acceptable", prompt)
        self.assertIn("2-4 concrete searchable words", prompt)

    def test_relevance_review_uses_topic_only_policy(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text="ACCEPT: צילום רלוונטי של רופאה ליד מכשיר רפואי"
        )

        accepted, description = social_image.review_relevance(
            client,
            b"photo-bytes",
            "image/jpeg",
            "בדיקה רפואית",
            "מידע על הבדיקה",
        )

        self.assertTrue(accepted)
        self.assertIn("רופאה", description)
        prompt = client.responses.create.call_args.kwargs["input"][0]["content"][0][
            "text"
        ]
        self.assertIn("Judge it only", prompt)
        self.assertIn("Do not reject it because it contains people", prompt)
        self.assertNotIn("Reject generic wellness imagery", prompt)
        self.assertNotIn("ANY visible letter", prompt)

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

    def test_openverse_search_preserves_commercial_license_provenance(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "results": [{
                "title": "Lab tube",
                "url": "https://images.example/lab.jpg",
                "foreign_landing_url": "https://source.example/lab",
                "creator": None,
                "license": "cc0",
                "license_version": "1.0",
                "license_url": (
                    "https://creativecommons.org/publicdomain/zero/1.0/"
                ),
                "filetype": "jpg",
                "category": "photograph",
                "width": 3872,
                "height": 2592,
                "tags": [{"name": "laboratory"}],
                "attribution": "Lab tube is CC0.",
            }]
        }
        request_get = Mock(return_value=response)

        candidates = social_image.search_openverse(
            "laboratory test tubes",
            request_get=request_get,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["license_name"], "CC0 1.0")
        self.assertEqual(
            candidates[0]["source_type"],
            "openverse_licensed_photo",
        )
        params = request_get.call_args.kwargs["params"]
        self.assertEqual(params["license_type"], "commercial")
        self.assertEqual(params["category"], "photograph")

    @patch.dict(os.environ, {"PEXELS_API_KEY": "pexels-key"}, clear=True)
    def test_pexels_search_preserves_source_and_license(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"photos": [{
            "width": 2400,
            "height": 1600,
            "url": "https://www.pexels.com/photo/123/",
            "photographer": "Jane Example",
            "alt": "Therapy dog in a rehabilitation room",
            "src": {"large2x": "https://images.pexels.com/photos/123.jpeg"},
        }]}
        candidates = social_image.search_pexels(
            "therapy dog rehabilitation", request_get=Mock(return_value=response)
        )
        self.assertEqual(candidates[0]["source_type"], "pexels_free_photo")
        self.assertEqual(candidates[0]["license_name"], "Pexels License")
        self.assertIn("Jane Example", candidates[0]["attribution"])

    @patch.dict(os.environ, {"PIXABAY_API_KEY": "pixabay-key"}, clear=True)
    def test_pixabay_search_preserves_source_and_license(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"hits": [{
            "imageWidth": 2400,
            "imageHeight": 1600,
            "largeImageURL": "https://pixabay.com/get/dog.jpg",
            "pageURL": "https://pixabay.com/photos/dog-123/",
            "user": "John Example",
            "tags": "therapy dog, rehabilitation",
        }]}
        candidates = social_image.search_pixabay(
            "therapy dog rehabilitation", request_get=Mock(return_value=response)
        )
        self.assertEqual(candidates[0]["source_type"], "pixabay_free_photo")
        self.assertIn("Pixabay Content License", candidates[0]["license_name"])

    def test_known_topic_uses_deterministic_queries_without_planner_cost(self):
        client = Mock()
        with patch(
            "scripts.social_image.search_commons",
            return_value=[],
        ) as search, patch(
            "scripts.social_image.search_openverse",
            return_value=[],
        ):
            with self.assertRaises(social_image.PhotoSelectionError):
                social_image.select_licensed_photo(
                    "תסמונת השחלות הפוליציסטיות",
                    "אבחון וטיפול",
                    client=client,
                )
        client.responses.create.assert_not_called()
        searched = [call.args[0] for call in search.call_args_list]
        self.assertIn("gynecological ultrasound equipment", searched)

    def test_failed_topics_have_direct_deterministic_queries(self):
        self.assertIn(
            "experiencing menstrual pain",
            social_image.topic_search_queries("כאבי מחזור קשים"),
        )
        self.assertIn(
            "night duty hospital",
            social_image.topic_search_queries("משמרות לילה משבשות את הגוף"),
        )
        self.assertIn(
            "therapy dog rehabilitation",
            social_image.topic_search_queries("כלבי טיפול בשיקום לאחר שבץ"),
        )

    @patch("scripts.social_image.search_openverse", return_value=[])
    @patch("scripts.social_image.search_commons", return_value=[])
    def test_generate_reports_search_diagnostics_when_no_photo_is_found(
        self, search, _openverse
    ):
        planned = [
            "adult comparing health information laptop",
            "person reading medical reference book",
            "library health research",
            "tablet health information research",
            "adult studying reference sources",
        ]
        expected_searches = len(
            social_image.expand_search_queries(
                social_image.topic_search_queries("איך להעריך מידע רפואי ברשת")
            )
        )
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

    @patch("scripts.social_image.search_openverse", return_value=[])
    @patch("scripts.social_image.search_commons", return_value=[])
    def test_commons_selector_falls_back_when_planner_fails(
        self, search, _openverse
    ):
        client = Mock()
        client.responses.create.side_effect = TimeoutError("planner unavailable")

        with self.assertRaisesRegex(
            social_image.PhotoSelectionError,
            "No suitably licensed",
        ):
            social_image.select_licensed_photo("כותרת", "תקציר", client=client)
        searched = [call.args[0] for call in search.call_args_list]
        self.assertIn("medical research equipment", searched)

    @patch("scripts.social_image.review_relevance")
    @patch("scripts.social_image.requests.get")
    @patch("scripts.social_image.search_openverse", return_value=[])
    @patch("scripts.social_image.search_commons")
    def test_commons_selector_can_still_select_a_licensed_photo(
        self, search, _openverse, get, review
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

    @patch("scripts.social_image.requests.get")
    @patch("scripts.social_image.search_openverse", return_value=[])
    @patch("scripts.social_image.search_commons")
    @patch("scripts.social_image.build_search_queries")
    @patch("scripts.social_image.review_relevance")
    def test_selector_moves_to_next_query_after_two_rejections(
        self, review, planner, search, _openverse, get
    ):
        planner.return_value = [
            "first medical query",
            "second medical query",
            "third medical query",
        ]
        candidate = {
            "download_url": "https://upload.wikimedia.org/photo.jpg",
            "source_image_url": "",
            "source_page_url": "https://commons.wikimedia.org/wiki/File:Photo.jpg",
            "creator": "Photographer",
            "license_name": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "attribution": "Photo",
            "media_type": "image/jpeg",
            "extension": "jpg",
        }
        search.side_effect = [
            [
                {**candidate, "source_image_url": "https://example.com/one.jpg"},
                {**candidate, "source_image_url": "https://example.com/two.jpg"},
            ],
            [{**candidate, "source_image_url": "https://example.com/three.jpg"}],
        ]
        get.return_value.content = b"x" * 25_000
        get.return_value.raise_for_status.return_value = None
        review.side_effect = [
            (False, "לא מתאים"),
            (False, "עדיין לא מתאים"),
            (True, "צילום רלוונטי ללא מלל"),
        ]

        selected = social_image.select_licensed_photo(
            "כותרת רפואית",
            "תקציר",
            client=Mock(),
        )

        self.assertEqual(selected.visual_description, "צילום רלוונטי ללא מלל")
        self.assertEqual(search.call_count, 2)

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
    def test_generate_uses_owner_default_without_creating_an_ai_image(self, select):
        client = Mock()
        result = social_image.generate("כותרת", "תקציר", client=client)

        self.assertEqual(result.source_type, "owner_provided_default")
        self.assertEqual(
            set(result.variants),
            {"hero", "landscape", "square", "portrait"},
        )
        self.assertEqual(Image.open(BytesIO(result.variants["hero"])).size, (1600, 900))
        self.assertEqual(
            Image.open(BytesIO(result.variants["portrait"])).size,
            (1080, 1350),
        )
        self.assertFalse(hasattr(client, "images") and client.images.generate.called)

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
        get.assert_called_once_with(
            "https://guyrofe.com/wp-json/wp/v2/media",
            auth=("user", "password"),
            params={"slug": "approved-social", "_fields": "id,source_url,slug"},
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": "ReputationAgentPublisher/1.0 (+https://guyrofe.com)",
            },
            timeout=25,
        )
        post.assert_not_called()

    @patch("scripts.social_image.requests.get")
    def test_wordpress_lookup_object_returns_actionable_error(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "code": "rest_forbidden",
            "message": "Authentication required",
        }
        get.return_value = response
        with self.assertRaisesRegex(RuntimeError, "rest_forbidden.*Authentication"):
            social_image.upload_to_wordpress(
                social_image.SocialImage(b"image"),
                base_url="https://example.com",
                username="user",
                app_password="password",
                slug="approved-social",
                title="כותרת",
            )

    @patch("scripts.social_image.time.sleep")
    @patch("scripts.social_image.requests.post")
    @patch("scripts.social_image.requests.get")
    def test_wordpress_lookup_retries_transient_connect_timeout(
        self, get, post, sleep
    ):
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = [
            {"id": 7, "source_url": "https://guyrofe.com/image.png"}
        ]
        get.side_effect = [requests.ConnectTimeout("temporary"), response]

        url = social_image.upload_to_wordpress(
            social_image.SocialImage(b"image"),
            base_url="https://guyrofe.com",
            username="user",
            app_password="password",
            slug="approved-social",
            title="כותרת",
        )

        self.assertEqual(url, "https://guyrofe.com/image.png")
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)
        post.assert_not_called()

    @patch("scripts.social_image.time.sleep")
    @patch("scripts.social_image.requests.get")
    def test_wordpress_lookup_retries_invalid_json_then_explains_failure(
        self, get, sleep
    ):
        response = Mock(status_code=200, headers={"Content-Type": "text/html"})
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("not JSON")
        get.return_value = response

        with self.assertRaisesRegex(
            RuntimeError, "non-JSON response.*text/html"
        ):
            social_image.upload_to_wordpress(
                social_image.SocialImage(b"image"),
                base_url="https://guyrofe.com",
                username="user",
                app_password="password",
                slug="approved-social",
                title="כותרת",
            )

        self.assertEqual(get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_generated_instagram_square_is_jpeg(self):
        source = BytesIO()
        Image.new("RGB", (1600, 1200), "#64858a").save(source, format="JPEG")
        licensed = social_image.SocialImage(
            content=source.getvalue(),
            visual_description="צילום רפואי רלוונטי",
            source_type="pexels_free_photo",
        )
        with patch("scripts.social_image.select_licensed_photo", return_value=licensed):
            result = social_image.generate("כותרת", "תקציר", client=Mock())
        self.assertEqual(Image.open(BytesIO(result.variants["square"])).format, "JPEG")

    @patch.dict(
        os.environ,
        {"INSTAGRAM_BUSINESS_ID": "ig", "FACEBOOK_PAGE_TOKEN": "token"},
        clear=True,
    )
    @patch("scripts.social_publishers.meta.requests.post")
    def test_instagram_error_preserves_meta_fields(self, post):
        response = Mock(ok=False, status_code=400)
        response.json.return_value = {"error": {
            "message": "Only photo or video can be accepted",
            "code": 9004,
            "error_subcode": 2207052,
            "fbtrace_id": "trace-test",
        }}
        post.return_value = response
        with self.assertRaisesRegex(RuntimeError, "code=9004.*error_subcode=2207052"):
            meta.publish_instagram(
                "כותרת", "מידע", "https://example.com/post", "https://example.com/image.jpg"
            )

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
            "ד״ר גיא רופא אינו מקבל כיום מטופלות.",
        )
        content = post.call_args.kwargs["json"]["content"]
        self.assertIn('alt="ד״ר גיא רופא — איור מידע כללי"', content)
        self.assertLess(
            content.index("https://guyrofe.com/article"),
            content.index("<small>"),
        )
        self.assertTrue(content.endswith("</small></p>"))

    @patch.dict(os.environ, {"BLOGGER_BLOG_ID": "blog"}, clear=True)
    @patch("scripts.social_publishers.blogger.requests.get")
    def test_blogger_reconcile_requires_exact_title_and_canonical_link(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [
                {
                    "id": "wrong",
                    "title": "כותרת דומה",
                    "content": '<a href="https://guyrofe.com/article">קישור</a>',
                    "url": "https://example.blogspot.com/wrong",
                },
                {
                    "id": "right",
                    "title": "כותרת",
                    "content": '<a href="https://guyrofe.com/article">קישור</a>',
                    "url": "https://example.blogspot.com/right",
                    "published": "2026-08-05T00:00:00Z",
                },
            ]
        }
        get.return_value = response

        receipt = blogger.reconcile(
            "כותרת", "https://guyrofe.com/article", access_token="token"
        )

        self.assertEqual(receipt["url"], "https://example.blogspot.com/right")
        self.assertEqual(receipt["provider_receipt"]["id"], "right")
        self.assertEqual(get.call_args.kwargs["params"]["q"], "כותרת")

    @patch.dict(os.environ, {"BLOGGER_BLOG_ID": "blog"}, clear=True)
    @patch("scripts.social_publishers.blogger.requests.get")
    def test_blogger_reconcile_returns_none_without_exact_canonical_link(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [
                {
                    "title": "כותרת",
                    "content": '<a href="https://guyrofe.com/other">קישור</a>',
                    "url": "https://example.blogspot.com/other",
                }
            ]
        }
        get.return_value = response

        self.assertIsNone(
            blogger.reconcile(
                "כותרת", "https://guyrofe.com/article", access_token="token"
            )
        )

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
