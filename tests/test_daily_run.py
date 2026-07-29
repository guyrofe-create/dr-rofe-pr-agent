import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import daily_run
from scripts.reputation_core.entity_contract import apply_article_contract


INLINE_EVIDENCE = (
    "לפי [הנחיית ארגון הבריאות העולמי בנושא](https://www.who.int/example), "
    "יש לבסס מידע על ראיות. גם "
    "[הנחיות ACOG למידע רפואי](https://www.acog.org/example) "
    "מדגישות שימוש במקורות מוסדיים.\n\n"
)


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

            self.assertRegex(
                path.name,
                r"^2026-07-25-topic-03-093000-\d{6}\.md$",
            )
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

    def test_repeated_runs_rotate_to_the_least_recently_used_topic(self):
        topics = ["נושא א", "נושא ב", "נושא ג"]
        now = datetime(2026, 7, 27, 9, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.json").write_text(
                json.dumps(
                    {
                        "drafts": [
                            {
                                "topic": "נושא א",
                                "generated_at": "2026-07-27T09:00:00+00:00",
                            },
                            {
                                "topic": "נושא ב",
                                "generated_at": "2026-07-26T09:00:00+00:00",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.object(daily_run, "TOPICS", topics),
                patch.dict(os.environ, {"CONTENT_DRAFT_DIR": directory}),
            ):
                _, topic = daily_run.selected_topic(now)
            self.assertEqual(topic, "נושא ג")

    def test_topic_rotation_reuses_only_the_oldest_after_full_cycle(self):
        topics = ["נושא א", "נושא ב", "נושא ג"]
        now = datetime(2026, 7, 27, 9, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.json").write_text(
                json.dumps(
                    {
                        "drafts": [
                            {
                                "topic": "נושא א",
                                "generated_at": "2026-07-27T09:00:00+00:00",
                            },
                            {
                                "topic": "נושא ב",
                                "generated_at": "2026-07-26T09:00:00+00:00",
                            },
                            {
                                "topic": "נושא ג",
                                "generated_at": "2026-07-25T09:00:00+00:00",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with (
                patch.object(daily_run, "TOPICS", topics),
                patch.dict(os.environ, {"CONTENT_DRAFT_DIR": directory}),
            ):
                _, topic = daily_run.selected_topic(now)
            self.assertEqual(topic, "נושא ג")

    def test_each_github_run_gets_its_own_draft_path(self):
        with tempfile.TemporaryDirectory() as directory:
            now = datetime(2026, 7, 25, 9, 30, tzinfo=timezone.utc)
            with patch.dict(
                os.environ,
                {
                    "CONTENT_DRAFT_DIR": directory,
                    "GITHUB_RUN_ID": "12345",
                    "GITHUB_RUN_ATTEMPT": "2",
                },
                clear=False,
            ):
                path = daily_run.save_draft(
                    3, "נושא", "כותרת", "# כותרת\n\nתוכן", now=now
                )
            self.assertEqual(
                path.name,
                "2026-07-25-topic-03-run-12345-attempt-2.md",
            )

    def test_generated_markdown_code_fence_is_removed(self):
        content = "```markdown\n# כותרת\n\nתוכן\n```"
        self.assertEqual(
            daily_run.clean_generated_markdown(content),
            "# כותרת\n\nתוכן",
        )

    def test_short_generated_article_fails_quality_gate(self):
        with self.assertRaisesRegex(ValueError, "words"):
            daily_run.validate_generated_article("# כותרת\n\nטקסט קצר מדי")

    def test_valid_generated_article_passes_quality_gate(self):
        content = "# כותרת\n\n" + INLINE_EVIDENCE + " ".join(
            ["מידע"] * daily_run.MIN_ARTICLE_WORDS
        ) + (
            "\n\n## מקורות\n"
            "- https://www.who.int/example\n"
            "- https://www.acog.org/example\n"
        )
        content = apply_article_contract(content, daily_run.CLIENT_PROFILE)
        title, word_count = daily_run.validate_generated_article(content)
        self.assertEqual(title, "כותרת | ד״ר גיא רופא")
        self.assertGreaterEqual(word_count, daily_run.MIN_ARTICLE_WORDS)

    def test_entity_contract_is_required_after_other_quality_checks(self):
        content = "# כותרת\n\n" + INLINE_EVIDENCE + " ".join(
            ["מידע"] * daily_run.MIN_ARTICLE_WORDS
        ) + (
            "\n\n## מקורות\n"
            "- https://www.who.int/example\n"
            "- https://www.acog.org/example\n"
        )
        with self.assertRaisesRegex(ValueError, "entity contract"):
            daily_run.validate_generated_article(content)

    def test_generated_medical_article_requires_two_direct_sources(self):
        content = "# כותרת\n\n" + " ".join(
            ["מידע"] * daily_run.MIN_ARTICLE_WORDS
        ) + "\n\n## מקורות\n- https://www.who.int/example\n"
        with self.assertRaisesRegex(ValueError, "at least 2"):
            daily_run.validate_generated_article(content)

    def test_generated_medical_article_requires_inline_evidence_links(self):
        content = "# כותרת\n\n" + " ".join(
            ["מידע"] * daily_run.MIN_ARTICLE_WORDS
        ) + (
            "\n\n## מקורות\n"
            "- https://www.who.int/example\n"
            "- https://www.acog.org/example\n"
        )
        content = apply_article_contract(content, daily_run.CLIENT_PROFILE)
        with self.assertRaisesRegex(ValueError, "inline evidence"):
            daily_run.validate_generated_article(content)

    def test_generated_medical_article_rejects_unapproved_source_domain(self):
        content = "# כותרת\n\n" + INLINE_EVIDENCE + " ".join(
            ["מידע"] * daily_run.MIN_ARTICLE_WORDS
        ) + (
            "\n\n## מקורות\n"
            "- https://www.who.int/example\n"
            "- https://www.acog.org/example\n"
            "- https://medical-marketing-blog.example/article\n"
        )
        with self.assertRaisesRegex(ValueError, "non-approved"):
            daily_run.validate_generated_article(content)

    def test_generated_medical_article_requires_two_institutional_sources(self):
        content = (
            "# כותרת\n\n"
            "לפי [מחקר ראשון בנושא](https://doi.org/10.1000/example-one) "
            "ולפי [מחקר נוסף בנושא](https://doi.org/10.1000/example-two), "
            "המידע דורש בדיקה.\n\n"
            + " ".join(
            ["מידע"] * daily_run.MIN_ARTICLE_WORDS
            )
            + (
            "\n\n## מקורות\n"
            "- https://doi.org/10.1000/example-one\n"
            "- https://doi.org/10.1000/example-two\n"
            )
        )
        with self.assertRaisesRegex(ValueError, "institutional"):
            daily_run.validate_generated_article(content)

    def test_generation_retry_expands_the_previous_draft(self):
        messages = daily_run.generation_messages(
            "כתוב מאמר",
            previous_content="# כותרת\n\nטיוטה קצרה",
            last_error="generated article has 454 words",
        )
        self.assertEqual(
            [message["role"] for message in messages],
            ["user", "assistant", "user"],
        )
        self.assertIn("טיוטה קצרה", messages[1]["content"])
        self.assertIn("הרחב", messages[2]["content"])
        self.assertIn("אל תתחיל", messages[2]["content"])
        self.assertIn("הסר אותו", messages[2]["content"])
        self.assertIn("סעיף המקורות", messages[2]["content"])

    def test_inline_sources_are_synchronized_without_model_retry(self):
        content = (
            "# כותרת\n\n"
            "לפי [הנחיית ארגון הבריאות העולמי]"
            "(https://www.who.int/example), נדרשת בדיקה.\n\n"
            "## מקורות\n"
            "- https://www.acog.org/example\n"
        )
        synchronized = daily_run.synchronize_inline_sources(content)
        self.assertIn(
            "- [הנחיית ארגון הבריאות העולמי](https://www.who.int/example)",
            synchronized,
        )
        self.assertEqual(synchronized.count("https://www.who.int/example"), 2)

    def test_generation_uses_responses_api_with_high_verbosity(self):
        client = Mock()
        client.responses.create.return_value.output_text = "# כותרת\n\nתוכן"

        with patch.dict(os.environ, {}, clear=True):
            content = daily_run.request_generated_article(
                client,
                [{"role": "user", "content": "כתוב מאמר"}],
            )

        self.assertEqual(content, "# כותרת\n\nתוכן")
        client.responses.create.assert_called_once_with(
            model="gpt-5.6",
            input=[{"role": "user", "content": "כתוב מאמר"}],
            reasoning={"effort": "low"},
            text={"verbosity": "high"},
            max_output_tokens=4500,
        )

    def test_news_analysis_uses_web_search_tool(self):
        client = Mock()
        client.responses.create.return_value.output_text = "# כותרת\n\nתוכן"
        daily_run.request_generated_article(
            client,
            [{"role": "user", "content": "נתח כתבה"}],
            use_web_search=True,
        )
        self.assertEqual(
            client.responses.create.call_args.kwargs["tools"],
            [{"type": "web_search"}],
        )

    def test_news_url_is_allowed_only_when_explicitly_required(self):
        news_url = "https://www.ynet.co.il/health/article/example"
        content = (
            "# כותרת\n\n"
            f"לפי [כתבת החדשות הנבדקת]({news_url}), נדרשת בדיקה. "
            + INLINE_EVIDENCE
            + " ".join(["מידע"] * daily_run.MIN_ARTICLE_WORDS)
            + (
                "\n\n## מקורות\n"
                f"- {news_url}\n"
                "- https://www.who.int/example\n"
                "- https://www.acog.org/example\n"
            )
        )
        content = apply_article_contract(content, daily_run.CLIENT_PROFILE)
        title, _word_count = daily_run.validate_generated_article(
            content,
            allowed_external_urls={news_url},
            required_urls={news_url},
        )
        self.assertIn("ד״ר גיא רופא", title)

    def test_content_model_can_be_overridden(self):
        client = Mock()
        client.responses.create.return_value.output_text = "טיוטה"

        with patch.dict(os.environ, {"OPENAI_CONTENT_MODEL": "custom-model"}):
            daily_run.request_generated_article(client, [])

        self.assertEqual(
            client.responses.create.call_args.kwargs["model"],
            "custom-model",
        )

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

    def test_generation_topics_do_not_claim_active_personal_practice(self):
        joined = "\n".join(daily_run.TOPICS)
        self.assertNotIn("ההכשרה שלי", joined)
        self.assertNotIn("עם מטופלת", joined)
        self.assertNotIn("זמינות ישירה לרופא", joined)

    def test_medium_publish_rechecks_publication_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "approved.md"
            draft.write_text(
                "# כותרת\n\nלקביעת תור צרו קשר", encoding="utf-8"
            )
            with patch.object(daily_run, "resolve_draft_path", return_value=draft):
                with self.assertRaisesRegex(ValueError, "publication.*policy"):
                    daily_run.publish_mode()


if __name__ == "__main__":
    unittest.main()
