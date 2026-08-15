import os
import unittest
from unittest.mock import Mock, patch

from scripts.social_publishers import google_business
from scripts.reputation_core.platform_content import build_platform_variants


class GoogleBusinessPublisherTests(unittest.TestCase):
    @patch("scripts.social_publishers.google_business.requests.get")
    def test_locations_use_business_information_api(self, get):
        response = Mock()
        response.json.return_value = {"locations": []}
        response.raise_for_status.return_value = None
        get.return_value = response

        google_business.list_locations("token", "accounts/12")

        self.assertEqual(
            get.call_args.args[0],
            "https://mybusinessbusinessinformation.googleapis.com/v1/"
            "accounts/12/locations",
        )
        self.assertEqual(
            get.call_args.kwargs["params"]["readMask"],
            "name,title,storeCode",
        )

    def test_variant_places_current_status_as_plain_final_sentence(self):
        variant = build_platform_variants(
            "אנדומטריוזיס ופוריות",
            "# אנדומטריוזיס ופוריות\n\nמידע רפואי כללי על הקשר בין הנושאים.",
            "https://guyrofe.com/endometriosis/",
        )["google_business"]
        disclosure = (
            "ד״ר גיא רופא אינו עוסק כיום ברפואה, אינו מקבל מטופלות "
            "ואינו מציע קביעת תורים."
        )
        self.assertTrue(variant["summary"].endswith(disclosure))
        self.assertNotIn(f"**{disclosure}**", variant["summary"])
        self.assertLessEqual(len(variant["summary"]), 700)

    def test_payload_is_information_only_with_photo_and_learn_more(self):
        payload = google_business._post_payload(
            "ד״ר גיא רופא: מידע רפואי כללי על אנדומטריוזיס.",
            "https://guyrofe.com/endometriosis/",
            "https://guyrofe.com/media/endometriosis.jpg",
        )
        self.assertEqual(payload["topicType"], "STANDARD")
        self.assertEqual(payload["callToAction"]["actionType"], "LEARN_MORE")
        self.assertEqual(payload["languageCode"], "he")
        self.assertEqual(payload["media"][0]["mediaFormat"], "PHOTO")

    def test_payload_rejects_booking_language(self):
        with self.assertRaisesRegex(ValueError, "publication policy"):
            google_business._post_payload(
                "לקביעת תור צרו קשר",
                "https://guyrofe.com/topic/",
                "https://guyrofe.com/media/topic.jpg",
            )

    def test_payload_requires_public_https_image(self):
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            google_business._post_payload(
                "ד״ר גיא רופא: מידע רפואי כללי.",
                "https://guyrofe.com/topic/",
                "/tmp/private.jpg",
            )

    def test_payload_rejects_homepage_or_unowned_link(self):
        for link in (
            "https://guyrofe.com/",
            "https://unowned.example/topic/",
        ):
            with self.subTest(link=link), self.assertRaisesRegex(
                ValueError, "topic page|official site"
            ):
                google_business._post_payload(
                    "ד״ר גיא רופא: מידע רפואי כללי.",
                    link,
                    "https://guyrofe.com/media/topic.jpg",
                )

    def test_unique_location_is_discovered_safely(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            google_business,
            "list_accounts",
            return_value=[{"name": "accounts/12"}],
        ), patch.object(
            google_business,
            "list_locations",
            return_value=[
                {"name": "locations/34", "locationName": "ד״ר גיא רופא"}
            ],
        ):
            account, location, metadata = google_business.resolve_location("token")
        self.assertEqual(account, "accounts/12")
        self.assertEqual(location, "accounts/12/locations/34")
        self.assertEqual(metadata["locationName"], "ד״ר גיא רופא")

    def test_multiple_locations_require_exact_ids(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            google_business,
            "list_accounts",
            return_value=[{"name": "accounts/12"}],
        ), patch.object(
            google_business,
            "list_locations",
            return_value=[
                {"name": "locations/34", "locationName": "א"},
                {"name": "locations/56", "locationName": "ב"},
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "Multiple"):
                google_business.resolve_location("token")

    @patch("scripts.social_publishers.google_business._existing_post")
    @patch("scripts.social_publishers.google_business.resolve_location")
    def test_reconcile_returns_none_when_exact_post_is_absent(
        self, resolve_location, existing_post
    ):
        resolve_location.return_value = (
            "accounts/12",
            "accounts/12/locations/34",
            {"locationName": "ד״ר גיא רופא"},
        )
        existing_post.return_value = None

        result = google_business.reconcile(
            "ד״ר גיא רופא: מידע רפואי כללי.",
            "https://guyrofe.com/topic/",
            "https://guyrofe.com/media/topic.jpg",
            access_token="token",
        )

        self.assertIsNone(result)

    @patch("scripts.social_publishers.google_business._existing_post")
    @patch("scripts.social_publishers.google_business.resolve_location")
    def test_reconcile_returns_receipt_for_exact_existing_post(
        self, resolve_location, existing_post
    ):
        resolve_location.return_value = (
            "accounts/12",
            "accounts/12/locations/34",
            {"locationName": "ד״ר גיא רופא"},
        )
        existing_post.return_value = {
            "name": "accounts/12/locations/34/localPosts/78",
            "state": "LIVE",
            "searchUrl": "https://posts.gle/example",
        }

        result = google_business.reconcile(
            "ד״ר גיא רופא: מידע רפואי כללי.",
            "https://guyrofe.com/topic/",
            "https://guyrofe.com/media/topic.jpg",
            access_token="token",
        )

        self.assertEqual(result["url"], "https://posts.gle/example")

    @patch("scripts.social_publishers.google_business.time.sleep")
    @patch("scripts.social_publishers.google_business.requests.get")
    @patch("scripts.social_publishers.google_business.requests.post")
    def test_publish_returns_google_search_receipt(self, post, get, _sleep):
        token_response = Mock()
        token_response.json.return_value = {"access_token": "token"}
        token_response.raise_for_status.return_value = None
        create_response = Mock()
        create_response.json.return_value = {
            "name": "accounts/12/locations/34/localPosts/78",
            "state": "LIVE",
            "searchUrl": "https://posts.gle/example",
        }
        create_response.raise_for_status.return_value = None
        post.side_effect = [token_response, create_response]

        duplicate_response = Mock()
        duplicate_response.json.return_value = {"localPosts": []}
        duplicate_response.raise_for_status.return_value = None
        get.return_value = duplicate_response

        with patch.object(
            google_business,
            "resolve_location",
            return_value=(
                "accounts/12",
                "accounts/12/locations/34",
                {"locationName": "ד״ר גיא רופא"},
            ),
        ), patch.dict(
            os.environ,
            {
                "GOOGLE_OAUTH_CLIENT_ID": "client",
                "GOOGLE_OAUTH_CLIENT_SECRET": "secret",
                "GOOGLE_OAUTH_REFRESH_TOKEN": "refresh",
            },
            clear=True,
        ):
            receipt = google_business.publish(
                "ד״ר גיא רופא: מידע רפואי כללי על אנדומטריוזיס.",
                "https://guyrofe.com/endometriosis/",
                "https://guyrofe.com/media/endometriosis.jpg",
            )
        self.assertEqual(receipt["url"], "https://posts.gle/example")
        self.assertEqual(receipt["provider_receipt"]["state"], "LIVE")
        self.assertEqual(
            post.call_args.kwargs["json"]["callToAction"]["actionType"],
            "LEARN_MORE",
        )


if __name__ == "__main__":
    unittest.main()
