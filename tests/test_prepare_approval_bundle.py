import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_approval_bundle
from scripts.reputation_core.approval_workflow import approve_bundle
from scripts.reputation_core.entity_contract import apply_article_contract


SECRET = "a-test-signing-secret-with-32-characters"


class PrepareApprovalBundleTests(unittest.TestCase):
    def test_google_business_target_is_exact_short_information_payload(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "google-business.md"
            content = apply_article_contract(
                (
                    "# אנדומטריוזיס ופוריות\n\n"
                    "מידע רפואי כללי על הקשר בין אנדומטריוזיס ופוריות.\n\n"
                    "## מקורות\n"
                    "[מקור רשמי](https://www.who.int/health-topics/)\n"
                ),
                prepare_approval_bundle.load_client_profile(),
            )
            draft.write_text(content, encoding="utf-8")
            result = prepare_approval_bundle.prepare_bundle(
                draft,
                output_root=root / "bundles",
                image_uri="https://example.com/approved.jpg",
                image_alt_text="צילום מאושר בנושא אנדומטריוזיס",
                image_metadata={
                    "variants": {
                        "landscape": {
                            "uri": "https://example.com/approved-landscape.jpg",
                            "sha256": "a" * 64,
                            "width": 1200,
                            "height": 630,
                        }
                    }
                },
                channel_ids=["google_business"],
            )
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
        targets = {item["target_id"]: item for item in bundle["targets"]}
        self.assertEqual(
            set(targets), {"canonical_wordpress", "google_business_profile"}
        )
        payload = targets["google_business_profile"]["payload"]
        self.assertEqual(payload["topic_type"], "STANDARD")
        self.assertEqual(payload["call_to_action"], "LEARN_MORE")
        self.assertTrue(payload["information_only"])
        self.assertFalse(payload["booking_or_contact_cta"])
        self.assertEqual(payload["image"]["role"], "landscape")
        self.assertIn("ד״ר גיא רופא", payload["summary"])
        self.assertLessEqual(len(payload["summary"]), 700)

    def test_evergreen_wix_bundle_uses_only_the_primary_wix_site(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "evergreen.md"
            content = apply_article_contract(
                (
                    "# מדריך רפואי ירוק עד\n\n"
                    "מידע רפואי כללי ומקורי המבוסס על מקור מוסדי.\n\n"
                    "## מקורות\n"
                    "[מקור רשמי](https://www.who.int/health-topics/)\n"
                ),
                prepare_approval_bundle.load_client_profile(),
            )
            draft.write_text(
                '<!--\ncontent_stream: "evergreen_knowledge"\n'
                'destination_site_key: "DRGUYROFE_COM"\n-->\n\n'
                + content,
                encoding="utf-8",
            )
            result = prepare_approval_bundle.prepare_bundle(
                draft,
                output_root=root / "bundles",
                image_uri="https://example.com/approved.jpg",
                image_alt_text="צילום רפואי מאושר",
                channel_ids=[],
            )
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
        self.assertEqual(len(bundle["targets"]), 1)
        target = bundle["targets"][0]
        self.assertEqual(target["target_id"], "canonical_wix")
        self.assertEqual(target["payload"]["site_key"], "DRGUYROFE_COM")
        self.assertIn("/post/", target["payload"]["canonical_url"])
        self.assertTrue(
            bundle["compliance"]["cross_domain_originality_checked"]
        )

    def test_scheduled_bundle_targets_drguyrofe_and_only_selected_channels(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "news.md"
            content = apply_article_contract(
                (
                    "# ניתוח חדשות רפואיות\n\n"
                    "מידע רפואי כללי המבוסס על מקורות.\n\n"
                    "## מקורות\n"
                    "- https://www.who.int/example\n"
                ),
                prepare_approval_bundle.load_client_profile(),
            )
            draft.write_text(content, encoding="utf-8")
            result = prepare_approval_bundle.prepare_bundle(
                draft,
                output_root=root / "bundles",
                image_uri="https://example.com/approved.jpg",
                image_alt_text="צילום מאושר בנושא המאמר",
                image_metadata={
                    "variants": {
                        "square": {
                            "uri": "https://example.com/approved-square.jpg",
                            "sha256": "a" * 64,
                            "width": 1200,
                            "height": 1200,
                        }
                    }
                },
                site_key="DRGUYROFE_CO_IL",
                channel_ids=["facebook", "instagram"],
            )
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
        targets = {item["target_id"]: item for item in bundle["targets"]}
        self.assertEqual(
            set(targets),
            {"canonical_wordpress", "facebook_page", "instagram_business"},
        )
        canonical = targets["canonical_wordpress"]["payload"]
        self.assertEqual(canonical["site_key"], "DRGUYROFE_CO_IL")
        self.assertTrue(
            canonical["canonical_url"].startswith("https://www.drguyrofe.co.il/")
        )
        self.assertEqual(
            targets["instagram_business"]["payload"]["image"]["role"],
            "square",
        )

    def test_prepares_exact_medical_bundle_and_preview_without_publication(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "medical.md"
            content = (
                "# מידע כללי\n\n"
                "זהו מידע כללי המבוסס על מקור רשמי ואינו תחליף לייעוץ רפואי. "
                "הטקסט מסביר את הנושא באופן מדויק ונגיש לקוראים.\n\n"
                "## מקורות\n\n"
                "[מקור רשמי](https://www.who.int/health-topics/)\n"
            )
            draft.write_text(
                apply_article_contract(
                    content,
                    prepare_approval_bundle.load_client_profile(),
                ),
                encoding="utf-8",
            )
            output = root / "bundles"
            result = prepare_approval_bundle.prepare_bundle(
                draft,
                output_root=output,
                image_uri="https://example.com/approved.png",
                image_alt_text="איור מופשט מאושר המתאר מידע כללי",
            )
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
            preview = Path(result["preview_path"]).read_text(encoding="utf-8")
            self.assertEqual(
                set(result["required_approval_scopes"]),
                {"public_publication", "medical_content"},
            )
            self.assertEqual(bundle["targets"][1]["platform"], "Facebook")
            self.assertIn("text", bundle["targets"][1]["payload"])
            self.assertEqual(
                bundle["media"]["alt_text"],
                "איור מופשט מאושר המתאר מידע כללי",
            )
            self.assertIn("https://www.who.int/health-topics/", preview)
            self.assertIn("Facebook", preview)

    def test_unexpected_image_pipeline_failure_cannot_create_an_imageless_bundle(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "medical.md"
            content = (
                "# הערכת מידע רפואי\n\n"
                "מידע כללי על בדיקת מקורות רפואיים ברשת ועל השוואת מידע.\n\n"
                "## מקורות\n\n"
                "[מקור רשמי](https://www.who.int/health-topics/)\n"
            )
            draft.write_text(
                apply_article_contract(
                    content,
                    prepare_approval_bundle.load_client_profile(),
                ),
                encoding="utf-8",
            )
            output = root / "bundles"
            result_path = root / "result.json"
            with patch.object(
                prepare_approval_bundle.social_image,
                "generate",
                side_effect=RuntimeError("rendering engine unavailable"),
            ), patch.dict(
                os.environ,
                {"PAID_IMAGE_SEARCH_ENABLED": "true"},
            ), patch.object(
                sys,
                "argv",
                [
                    "prepare_approval_bundle.py",
                    str(draft),
                    "--output-root",
                    str(output),
                    "--find-licensed-image",
                    "--result-path",
                    str(result_path),
                ],
            ), self.assertRaisesRegex(
                RuntimeError,
                "licensed-photo search failed without creating an AI image",
            ):
                prepare_approval_bundle.main()

            self.assertFalse(result_path.exists())
            self.assertFalse((output / "index.json").exists())

    def test_photo_selection_indecision_uses_owner_default_image(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "medical.md"
            content = (
                "# מידע רפואי\n\n"
                "תשובה ישירה וברורה המבוססת על מקורות מוסדיים.\n\n"
                "## הסבר\n\nפירוט שימושי.\n\n"
                "## מקורות\n\n"
                "[מקור](https://www.who.int/health-topics/)\n"
            )
            draft.write_text(
                apply_article_contract(
                    content,
                    prepare_approval_bundle.load_client_profile(),
                ),
                encoding="utf-8",
            )
            output = root / "bundles"
            result_path = root / "result.json"
            with patch.object(
                prepare_approval_bundle.social_image,
                "generate",
                side_effect=prepare_approval_bundle.social_image.PhotoSelectionError(
                    "no suitable licensed photograph"
                ),
            ), patch.object(
                sys,
                "argv",
                [
                    "prepare_approval_bundle.py",
                    str(draft),
                    "--output-root",
                    str(output),
                    "--find-licensed-image",
                    "--result-path",
                    str(result_path),
                ],
            ):
                prepare_approval_bundle.main()

            result = json.loads(result_path.read_text(encoding="utf-8"))
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
            index = json.loads((output / "index.json").read_text(encoding="utf-8"))
            self.assertEqual(result["image_status"], "ready")
            self.assertIn("no suitable licensed photograph", result["image_selection_error"])
            self.assertEqual(bundle["media"]["source_type"], "owner_provided_default")
            self.assertEqual(
                set(bundle["media"]["variants"]),
                {"hero", "landscape", "square", "portrait"},
            )
            self.assertEqual(index["bundles"][0]["image_status"], "ready")

    def test_missing_image_argument_uses_owner_default_image(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "default-image.md"
            content = (
                "# מידע רפואי\n\n"
                "תשובה ישירה וברורה המבוססת על מקורות מוסדיים.\n\n"
                "## הסבר\n\nפירוט שימושי.\n\n"
                "## מקורות\n\n"
                "[מקור](https://www.who.int/health-topics/)\n"
            )
            draft.write_text(
                apply_article_contract(
                    content,
                    prepare_approval_bundle.load_client_profile(),
                ),
                encoding="utf-8",
            )
            output = root / "bundles"
            result_path = root / "result.json"
            with patch.object(
                sys,
                "argv",
                [
                    "prepare_approval_bundle.py",
                    str(draft),
                    "--output-root",
                    str(output),
                    "--result-path",
                    str(result_path),
                ],
            ):
                prepare_approval_bundle.main()

            result = json.loads(result_path.read_text(encoding="utf-8"))
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result["image_status"], "ready")
            self.assertEqual(bundle["media"]["source_type"], "owner_provided_default")
            self.assertEqual(
                set(bundle["media"]["variants"]),
                {"hero", "landscape", "square", "portrait"},
            )

    def test_generation_saves_and_binds_all_approved_image_variants(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "medical.md"
            content = (
                "# מידע רפואי\n\n"
                "תשובה ישירה וברורה המבוססת על מקורות מוסדיים.\n\n"
                "## הסבר\n\nפירוט שימושי.\n\n"
                "## מקורות\n\n"
                "[מקור](https://www.who.int/health-topics/)\n"
            )
            draft.write_text(
                apply_article_contract(
                    content,
                    prepare_approval_bundle.load_client_profile(),
                ),
                encoding="utf-8",
            )
            output = root / "bundles"
            result_path = root / "result.json"
            image = prepare_approval_bundle.social_image.SocialImage(
                content=b"landscape",
                visual_description=(
                    "איור מערכתי ללא מלל בנושא מידע רפואי"
                ),
                source_type="wikimedia_commons_licensed_photo",
                source_page_url="https://commons.wikimedia.org/wiki/File:Medical.jpg",
                creator="Jane Example",
                license_name="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                attribution="Jane Example, CC BY 4.0",
                variants={
                    "hero": b"hero",
                    "landscape": b"landscape",
                    "square": b"square",
                    "portrait": b"portrait",
                },
            )

            with patch.object(
                prepare_approval_bundle.social_image,
                "generate",
                return_value=image,
            ), patch.dict(
                os.environ,
                {"PAID_IMAGE_SEARCH_ENABLED": "true"},
            ), patch.object(
                sys,
                "argv",
                [
                    "prepare_approval_bundle.py",
                    str(draft),
                    "--output-root",
                    str(output),
                    "--find-licensed-image",
                    "--result-path",
                    str(result_path),
                ],
            ):
                prepare_approval_bundle.main()

            result = json.loads(result_path.read_text(encoding="utf-8"))
            bundle = json.loads(
                Path(result["bundle_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result["image_status"], "ready")
            self.assertEqual(
                set(bundle["media"]["variants"]),
                {"hero", "landscape", "square", "portrait"},
            )
            targets = {
                item["target_id"]: item["payload"]["image"]["role"]
                for item in bundle["targets"]
            }
            self.assertEqual(targets["canonical_wordpress"], "hero")
            self.assertEqual(targets["facebook_page"], "landscape")
            self.assertEqual(targets["pinterest_board"], "portrait")
            self.assertIn("<img", Path(result["preview_path"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
