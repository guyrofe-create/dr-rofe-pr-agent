import json
import tempfile
import unittest
from pathlib import Path

from scripts import prepare_approval_bundle


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


if __name__ == "__main__":
    unittest.main()
