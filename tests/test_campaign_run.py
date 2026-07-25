import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import campaign_run
from scripts.social_publishers import common


class CampaignRunTests(unittest.TestCase):
    def test_stable_slug_keeps_hebrew_and_is_deterministic(self):
        self.assertEqual(
            campaign_run.stable_slug("לפני ניתוח: החלטה משותפת"),
            "לפני-ניתוח-החלטה-משותפת",
        )

    def test_first_paragraph_excludes_heading(self):
        content = "# כותרת\n\nפסקת פתיחה חשובה.\n\n## סעיף\n\nהמשך"
        self.assertEqual(
            campaign_run.first_paragraph(content),
            "פסקת פתיחה חשובה.",
        )

    def test_markdown_to_html_uses_wordpress_title_and_keeps_sections(self):
        rendered = campaign_run.markdown_to_html(
            "# כותרת\n\nפתיחה עם **הדגשה**.\n\n## סעיף\n\n[קישור](https://example.com)"
        )
        self.assertNotIn("<h1>", rendered)
        self.assertIn("<strong>הדגשה</strong>", rendered)
        self.assertIn("<h2>סעיף</h2>", rendered)
        self.assertIn('href="https://example.com"', rendered)

    def test_wordpress_publish_is_idempotent(self):
        get_response = Mock()
        get_response.json.return_value = [
            {"id": 42, "link": "https://guyrofe.com/existing"}
        ]
        get_response.raise_for_status.return_value = None
        with patch.object(
            campaign_run.requests, "get", return_value=get_response
        ) as get, patch.object(campaign_run.requests, "post") as post:
            url = campaign_run.wordpress_publish(
                "https://guyrofe.com",
                "user",
                "password",
                "כותרת",
                "<p>תוכן</p>",
                idempotency_key="dr-rofe-2026-07-25-topic-11",
            )
        self.assertEqual(url, "https://guyrofe.com/existing")
        post.assert_not_called()
        self.assertNotIn("auth", get.call_args.kwargs)
        self.assertEqual(
            get.call_args.kwargs["params"]["status"],
            "publish",
        )
        self.assertEqual(
            get.call_args.kwargs["params"]["slug"],
            "dr-rofe-2026-07-25-topic-11",
        )
        self.assertEqual(
            get.call_args.kwargs["headers"]["Accept"],
            "application/json",
        )

    def test_canonical_site_is_required_before_distribution(self):
        draft = Path(tempfile.mkdtemp()) / "draft.md"
        draft.write_text("# כותרת\n\nתוכן", encoding="utf-8")
        with patch.object(campaign_run, "load_draft", return_value=("כותרת", "# כותרת\n\nתוכן")), patch.dict(
            os.environ, {}, clear=True
        ):
            with self.assertRaisesRegex(RuntimeError, "Canonical"):
                campaign_run.publish_campaign(draft)

    def test_campaign_result_contains_destination_receipts(self):
        with tempfile.TemporaryDirectory(dir=campaign_run.PROJECT_ROOT) as directory:
            draft = Path(directory) / "approved.md"
            draft.write_text("# כותרת\n\nתוכן", encoding="utf-8")
            result_root = Path(directory) / "campaigns"
            with patch.object(campaign_run, "CAMPAIGN_ROOT", result_root):
                campaign_run.write_campaign_result(
                    draft,
                    "כותרת",
                    [
                        {
                            "name": "guyrofe.com",
                            "status": "published",
                            "url": "https://guyrofe.com/article",
                        }
                    ],
                )
            index = json.loads((result_root / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(index["campaigns"][0]["destinations"][0]["status"], "published")

    def test_social_caption_includes_approved_body_and_link(self):
        caption = common.shorten_for_social(
            "כותרת",
            "https://guyrofe.com/article",
            max_len=200,
            body="תקציר מאושר",
        )
        self.assertIn("תקציר מאושר", caption)
        self.assertIn("https://guyrofe.com/article", caption)


if __name__ == "__main__":
    unittest.main()
