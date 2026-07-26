import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import social_image
from scripts.social_publishers import meta


class SocialImageTests(unittest.TestCase):
    def test_prompt_excludes_medical_and_availability_claims(self):
        prompt = social_image.build_prompt("כותרת", "תקציר")
        self.assertIn("no text", prompt)
        self.assertIn("no doctor", prompt)
        self.assertIn("no surgery", prompt)
        self.assertIn("appointments are currently available", prompt)

    def test_generate_uses_current_image_model_and_decodes_png(self):
        client = Mock()
        client.images.generate.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(b"png-bytes").decode("ascii")
                )
            ]
        )
        with patch.dict(os.environ, {}, clear=True):
            result = social_image.generate("כותרת", "תקציר", client=client)
        self.assertEqual(result.content, b"png-bytes")
        self.assertEqual(
            client.images.generate.call_args.kwargs["model"], "gpt-image-2"
        )
        self.assertEqual(
            client.images.generate.call_args.kwargs["size"], "1024x1024"
        )

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
        )

        self.assertTrue(post.call_args.args[0].endswith("/123/photos"))
        self.assertEqual(
            post.call_args.kwargs["data"]["url"],
            "https://guyrofe.com/image.png",
        )


if __name__ == "__main__":
    unittest.main()
