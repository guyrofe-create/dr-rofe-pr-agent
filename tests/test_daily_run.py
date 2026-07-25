import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import daily_run


class DailyRunTests(unittest.TestCase):
    def setUp(self):
        daily_run.LOG_LINES.clear()

    def test_save_and_load_review_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 7, 25, 9, 30, tzinfo=timezone.utc)
            with patch.dict(os.environ, {"CONTENT_DRAFT_DIR": directory}):
                path = daily_run.save_draft(
                    3,
                    "נושא",
                    "כותרת",
                    "# כותרת\n\nתוכן רפואי לבדיקה",
                    now=now,
                )
                title, content = daily_run.load_draft(path)

            self.assertEqual(path.name, "2026-07-25-topic-03.md")
            self.assertEqual(title, "כותרת")
            self.assertIn("תוכן רפואי לבדיקה", content)
            self.assertIn("pending_medical_review", path.read_text(encoding="utf-8"))

    def test_draft_path_cannot_escape_review_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            outside = Path(directory).parent / "outside.md"
            outside.write_text("# Not approved\n", encoding="utf-8")
            self.addCleanup(outside.unlink, missing_ok=True)
            with patch.dict(os.environ, {"CONTENT_DRAFT_DIR": directory}):
                with self.assertRaisesRegex(ValueError, "inside"):
                    daily_run.resolve_draft_path(str(outside))

    def test_draft_index_is_created_for_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 7, 25, 9, 30, tzinfo=timezone.utc)
            with patch.dict(os.environ, {"CONTENT_DRAFT_DIR": directory}):
                daily_run.save_draft(
                    3, "נושא", "כותרת", "# כותרת\n\nתוכן רפואי לבדיקה", now=now
                )
            payload = (Path(directory) / "index.json").read_text(encoding="utf-8")
            self.assertIn('"path":', payload)
            self.assertIn("כותרת", payload)

    def test_publication_record_uses_dashboard_relative_draft_path(self):
        with tempfile.TemporaryDirectory(dir=daily_run.PROJECT_ROOT) as directory:
            draft_dir = Path(directory)
            draft = draft_dir / "approved.md"
            draft.write_text("# טיוטה מאושרת\n\nתוכן", encoding="utf-8")
            relative_dir = draft_dir.relative_to(daily_run.PROJECT_ROOT).as_posix()

            with patch.dict(os.environ, {"CONTENT_DRAFT_DIR": relative_dir}):
                daily_run.record_publication(
                    draft,
                    "https://medium.com/@doctor/approved-story",
                )

            publications = json.loads(
                (draft_dir / "publications.json").read_text(encoding="utf-8")
            )
            publication = publications["publications"][0]
            self.assertEqual(
                publication["draft"],
                f"{relative_dir}/approved.md",
            )
            self.assertFalse(Path(publication["draft"]).is_absolute())

    def test_navigation_uses_domcontentloaded_and_retries(self):
        page = Mock()
        page.goto.side_effect = [RuntimeError("temporary"), None]

        daily_run.goto_with_retry(page, "https://medium.com/new-story")

        self.assertEqual(page.goto.call_count, 2)
        for call in page.goto.call_args_list:
            self.assertEqual(call.kwargs["wait_until"], "domcontentloaded")
            self.assertEqual(call.kwargs["timeout"], 60_000)

    def test_run_log_is_created_after_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run_log.txt"
            daily_run.log("ERROR: example")
            daily_run.write_run_log(output)
            self.assertIn("ERROR: example", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
