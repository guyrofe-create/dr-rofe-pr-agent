import base64
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
        self.assertIn("איור עריכתי", text)
        self.assertIn("הקשורים ישירות", text)

    def test_alt_text_does_not_insert_name_when_entity_is_not_relevant(self):
        text = social_image.alt_text(
            "הסבר כללי",
            "איור מופשט כחול של צורות גאומטריות",
            entity_relevant=False,
        )
        self.assertNotIn("גיא רופא", text)
        self.assertIn("צורות גאומטריות", text)

    def test_prompt_excludes_medical_and_availability_claims(self):
        prompt = social_image.build_prompt(
            "כאבי מחזור קשים",
            "המאמר מסביר מתי כאב מחזור מצריך בירור ומהם סימני האזהרה",
        )
        self.assertIn("no text", prompt)
        self.assertIn("no doctor", prompt)
        self.assertIn("no surgery", prompt)
        self.assertIn("current service or appointment availability", prompt)
        self.assertIn("כאבי מחזור קשים", prompt)
        self.assertIn("סימני האזהרה", prompt)
        self.assertIn("MUST be unmistakably and specifically related", prompt)

    def test_generate_uses_current_image_model_and_decodes_png(self):
        client = Mock()
        client.images.generate.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(b"png-bytes").decode("ascii")
                )
            ]
        )
        client.responses.create.return_value = SimpleNamespace(
            output_text="RELATED: איור של לוח שנה וסמל כאב הקשורים לנושא"
        )
        with patch.dict(os.environ, {}, clear=True):
            result = social_image.generate("כותרת", "תקציר", client=client)
        self.assertEqual(result.content, b"png-bytes")
        self.assertIn("לוח שנה", result.visual_description)
        self.assertEqual(
            client.images.generate.call_args.kwargs["model"], "gpt-image-2"
        )
        self.assertEqual(
            client.images.generate.call_args.kwargs["size"], "1024x1024"
        )
        self.assertEqual(client.responses.create.call_count, 1)

    def test_unrelated_image_is_rejected_and_regenerated(self):
        client = Mock()
        client.images.generate.side_effect = [
            SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(b"generic").decode("ascii")
                    )
                ]
            ),
            SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=base64.b64encode(b"related").decode("ascii")
                    )
                ]
            ),
        ]
        client.responses.create.side_effect = [
            SimpleNamespace(
                output_text=(
                    "UNRELATED: show concrete symbols associated with menstrual pain"
                )
            ),
            SimpleNamespace(
                output_text="RELATED: איור של לוח שנה וכרית חימום"
            ),
        ]
        result = social_image.generate(
            "כאבי מחזור קשים",
            "מתי כאב מחזור מצריך בירור",
            client=client,
        )
        self.assertEqual(result.content, b"related")
        self.assertEqual(client.images.generate.call_count, 2)
        second_prompt = client.images.generate.call_args_list[1].kwargs["prompt"]
        self.assertIn("show concrete symbols", second_prompt)

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
