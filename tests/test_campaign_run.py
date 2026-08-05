import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import campaign_run
from scripts.social_publishers import common


class CampaignRunTests(unittest.TestCase):
    def test_resolves_approved_secondary_wordpress_site(self):
        business = campaign_run.load_business_profile()
        site = campaign_run.site_by_key(business, "DRGUYROFE_CO_IL")
        self.assertEqual(site["base_url"], "https://www.drguyrofe.co.il")

    def test_main_requires_signed_p7_approval_artifacts(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "APPROVAL_BUNDLE_PATH"):
                campaign_run.main()

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

    def test_author_disclosure_is_last_and_secondary_but_readable(self):
        rendered = campaign_run.markdown_to_html(
            "# כותרת\n\n## מקורות\n\n"
            "[מקור](https://example.com)\n\n"
            "## על המחבר\n\n"
            "ד״ר גיא רופא אינו עוסק כיום ברפואה."
        )
        self.assertGreater(
            rendered.index("author-disclosure"),
            rendered.index('href="https://example.com"'),
        )
        self.assertIn("font-size:0.9em", rendered)
        self.assertTrue(rendered.endswith("</section>"))

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

    def test_wordpress_payload_contains_meta_description(self):
        get_response = Mock()
        get_response.json.return_value = []
        get_response.raise_for_status.return_value = None
        post_response = Mock()
        post_response.json.return_value = {
            "id": 43,
            "link": "https://guyrofe.com/new",
        }
        post_response.raise_for_status.return_value = None
        with patch.object(
            campaign_run.requests, "get", return_value=get_response
        ), patch.object(
            campaign_run.requests, "post", return_value=post_response
        ) as post:
            campaign_run.wordpress_publish(
                "https://guyrofe.com",
                "user",
                "password",
                "כותרת | ד״ר גיא רופא",
                "<p>תוכן</p>",
                meta_description="ד״ר גיא רופא: תיאור מדויק",
            )
        self.assertEqual(
            post.call_args.kwargs["json"]["excerpt"],
            "ד״ר גיא רופא: תיאור מדויק",
        )

    def test_local_approved_image_requires_exact_hash(self):
        with tempfile.TemporaryDirectory(dir=campaign_run.PROJECT_ROOT) as directory:
            path = Path(directory) / "hero.png"
            path.write_bytes(b"approved-image")
            media = {
                "uri": path.resolve().relative_to(
                    campaign_run.PROJECT_ROOT
                ).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_type": "deterministic_text_free_fallback",
            }
            image, remote = campaign_run._load_approved_local_image(media)
            self.assertEqual(image.content, b"approved-image")
            self.assertEqual(remote, "")
            media["sha256"] = "0" * 64
            with self.assertRaisesRegex(PermissionError, "bytes"):
                campaign_run._load_approved_local_image(media)

    def test_embedded_manual_image_requires_exact_signed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manual.jpg"
            path.write_bytes(b"manually-approved-photo")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            media = {
                "uri": f"embedded://{digest}",
                "sha256": digest,
                "source_type": "owner_manual_upload",
                "alt_text": "צילום רפואי שאושר ידנית",
            }
            with patch.dict(
                os.environ, {"APPROVED_MEDIA_PATH": str(path)}, clear=False
            ):
                image, remote = campaign_run._load_approved_local_image(media)
            self.assertEqual(image.content, b"manually-approved-photo")
            self.assertEqual(image.source_type, "owner_manual_upload")
            self.assertEqual(remote, "")

    def test_embedded_manual_image_rejects_replaced_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manual.png"
            path.write_bytes(b"different-photo")
            media = {
                "uri": f"embedded://{'0' * 64}",
                "sha256": "0" * 64,
            }
            with patch.dict(
                os.environ, {"APPROVED_MEDIA_PATH": str(path)}, clear=False
            ):
                with self.assertRaisesRegex(PermissionError, "signed payload"):
                    campaign_run._load_approved_local_image(media)

    def test_canonical_site_is_required_before_distribution(self):
        draft = Path(tempfile.mkdtemp()) / "draft.md"
        draft.write_text("# כותרת\n\nתוכן", encoding="utf-8")
        bundle = {
            "source_draft": str(draft.resolve()),
            "source_draft_sha256": hashlib.sha256(draft.read_bytes()).hexdigest(),
            "targets": [],
        }
        with patch.object(campaign_run, "load_draft", return_value=("כותרת", "# כותרת\n\nתוכן")), patch.dict(
            os.environ, {}, clear=True
        ):
            with self.assertRaisesRegex(RuntimeError, "Canonical"):
                campaign_run.publish_campaign(draft, approved_bundle=bundle)

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
            self.assertIn("execution_receipt_ledger", index["campaigns"][0])

    def test_social_caption_includes_approved_body_and_link(self):
        caption = common.shorten_for_social(
            "כותרת",
            "https://guyrofe.com/article",
            max_len=200,
            body="תקציר מאושר",
        )
        self.assertIn("תקציר מאושר", caption)
        self.assertIn("https://guyrofe.com/article", caption)

    def test_social_disclosure_is_plain_final_text_after_link(self):
        disclosure = "ד״ר גיא רופא אינו מקבל כיום מטופלות."
        caption = common.shorten_for_social(
            "כותרת",
            "https://guyrofe.com/article",
            max_len=240,
            body="תקציר מאושר",
            footer=disclosure,
        )
        self.assertLess(
            caption.index("https://guyrofe.com/article"),
            caption.index(disclosure),
        )
        self.assertTrue(caption.endswith(disclosure))

    def test_destination_failure_is_reported_without_stopping_other_targets(self):
        target = {
            "target_id": "facebook_page",
            "platform": "Facebook",
            "asset": "page",
            "payload": {"text": "approved"},
        }
        ledger = Mock()
        ledger.execute.side_effect = TimeoutError("provider unavailable")
        result = campaign_run._execute_target_safely(
            ledger,
            {"approval_id": "apr_test"},
            target,
            lambda _payload, _key: {"url": "https://example.com"},
        )
        self.assertEqual(result["name"], "Facebook")
        self.assertEqual(result["status"], "failed")
        self.assertIn("provider unavailable", result["detail"])

    def test_destination_reconciler_is_forwarded_to_execution_ledger(self):
        target = {
            "target_id": "blogger_blog",
            "platform": "Blogger",
            "asset": "blog",
            "payload": {"title": "approved"},
        }
        ledger = Mock()
        ledger.execute.return_value = {
            "url": "https://example.blogspot.com/post",
            "idempotency_key": "pub_test",
        }
        publisher = Mock()
        reconciler = Mock()

        result = campaign_run._execute_target_safely(
            ledger,
            {"approval_id": "apr_test"},
            target,
            publisher,
            reconciler=reconciler,
        )

        self.assertEqual(result["status"], "published")
        ledger.execute.assert_called_once_with(
            {"approval_id": "apr_test"},
            target,
            publisher,
            reconciler=reconciler,
        )


if __name__ == "__main__":
    unittest.main()
