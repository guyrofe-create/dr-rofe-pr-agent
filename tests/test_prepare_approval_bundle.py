import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_approval_bundle
from scripts.reputation_core.approval_workflow import approve_bundle


SECRET = "a-test-signing-secret-with-32-characters"


class PrepareApprovalBundleTests(unittest.TestCase):
    def test_prepares_exact_medical_bundle_and_preview_without_publication(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "medical.md"
            draft.write_text(
                "# מידע כללי\n\n"
                "זהו מידע כללי המבוסס על מקור רשמי ואינו תחליף לייעוץ רפואי. "
                "הטקסט מסביר את הנושא באופן מדויק ונגיש לקוראים.\n\n"
                "## מקורות\n\n"
                "[מקור רשמי](https://www.who.int/health-topics/)\n",
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

    def test_failed_photo_search_preserves_non_publishable_review_bundle(self):
        with tempfile.TemporaryDirectory(
            dir=prepare_approval_bundle.PROJECT_ROOT / "content_drafts"
        ) as directory:
            root = Path(directory)
            draft = root / "medical.md"
            draft.write_text(
                "# הערכת מידע רפואי\n\n"
                "מידע כללי על בדיקת מקורות רפואיים ברשת ועל השוואת מידע.\n\n"
                "## מקורות\n\n"
                "[מקור רשמי](https://www.who.int/health-topics/)\n",
                encoding="utf-8",
            )
            output = root / "bundles"
            result_path = root / "result.json"
            error = prepare_approval_bundle.social_image.PhotoSelectionError(
                "No suitable licensed photo; diagnostics: reviewed=0"
            )

            with patch.object(
                prepare_approval_bundle.social_image,
                "generate",
                side_effect=error,
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
            index = json.loads(
                Path(result["index_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(result["image_status"], "awaiting_replacement")
            self.assertIsNone(bundle["media"])
            self.assertEqual(
                index["bundles"][0]["image_status"],
                "awaiting_replacement",
            )
            with self.assertRaisesRegex(
                PermissionError,
                "waiting for a licensed image",
            ):
                approve_bundle(
                    bundle,
                    approved_by="owner",
                    approved_scopes=["public_publication", "medical_content"],
                    signing_secret=SECRET,
                )


if __name__ == "__main__":
    unittest.main()
