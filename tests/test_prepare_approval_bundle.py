import json
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
            ), patch.object(
                sys,
                "argv",
                [
                    "prepare_approval_bundle.py",
                    str(draft),
                    "--output-root",
                    str(output),
                    "--generate-image",
                    "--result-path",
                    str(result_path),
                ],
            ), self.assertRaisesRegex(
                RuntimeError,
                "guaranteed image pipeline failed",
            ):
                prepare_approval_bundle.main()

            self.assertFalse(result_path.exists())
            self.assertFalse((output / "index.json").exists())

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
                source_type="deterministic_text_free_fallback",
                generation_model="local-text-free-template-v1",
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
            ), patch.object(
                sys,
                "argv",
                [
                    "prepare_approval_bundle.py",
                    str(draft),
                    "--output-root",
                    str(output),
                    "--generate-image",
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
