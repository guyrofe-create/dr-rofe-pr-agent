import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import autonomous_content_run


class AutonomousContentRunTests(unittest.TestCase):
    def test_content_freeze_blocks_all_generation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            autonomous_content_run, "content_is_frozen", return_value=True
        ), patch.object(
            autonomous_content_run, "generate_job"
        ) as generate:
            root = Path(directory)
            manifest = autonomous_content_run.run(
                cadence_path=autonomous_content_run.DEFAULT_CADENCE,
                state_path=root / "state.json",
                news_brief_dir=root,
                manifest_path=root / "manifest.json",
                now=datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc),
            )
        generate.assert_not_called()
        self.assertEqual(
            manifest["skipped"][0]["reason"],
            "command_center_content_freeze",
        )

    def test_unused_news_brief_requires_the_news_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "health-news-valid.json").write_text(
                json.dumps({
                    "status": "draft_brief_requires_editorial_review",
                    "destination_site_key": "DRGUYROFE_CO_IL",
                    "analyzed_news_url": "https://news.example/story",
                    "created_at": "2026-07-29T05:00:00Z",
                }),
                encoding="utf-8",
            )
            selected = autonomous_content_run.unused_news_brief(
                root,
                {"generated": []},
                now=datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(selected[1]["analyzed_news_url"], "https://news.example/story")

    def test_stale_news_brief_is_not_used_to_fill_a_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "health-news-stale.json").write_text(
                json.dumps({
                    "status": "draft_brief_requires_editorial_review",
                    "destination_site_key": "DRGUYROFE_CO_IL",
                    "analyzed_news_url": "https://news.example/old",
                    "created_at": "2026-07-20T05:00:00Z",
                }),
                encoding="utf-8",
            )
            selected = autonomous_content_run.unused_news_brief(
                root,
                {"generated": []},
                now=datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc),
            )
        self.assertIsNone(selected)

    def test_generation_job_preserves_site_channels_and_approval_gate(self):
        job = {
            "stream": "canonical_depth",
            "site_key": "GUYROFE_COM",
            "channels": ["facebook", "linkedin"],
            "week": "2026-W31",
            "local_date": "2026-07-27",
            "weekday": "monday",
            "public_execution_allowed": False,
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            autonomous_content_run, "selected_topic", return_value=(1, "נושא")
        ), patch.object(
            autonomous_content_run,
            "generate_article",
            return_value=("כותרת", "# כותרת\n\nתוכן"),
        ), patch.object(
            autonomous_content_run,
            "save_draft",
            return_value=Path(directory) / "draft.md",
        ) as save:
            result = autonomous_content_run.generate_job(
                job,
                datetime(2026, 7, 27, 6, 0, tzinfo=timezone.utc),
                Path(directory),
            )
        self.assertEqual(result["destination_site_key"], "GUYROFE_COM")
        self.assertEqual(result["scheduled_channels"], ["facebook", "linkedin"])
        self.assertFalse(result["public_execution_allowed"])
        metadata = save.call_args.kwargs["metadata"]
        self.assertEqual(metadata["content_stream"], "canonical_depth")

    def test_evergreen_wix_job_has_a_distinct_editorial_context(self):
        job = {
            "stream": "evergreen_knowledge",
            "site_key": "DRGUYROFE_COM",
            "channels": [],
            "week": "week-of-2026-07-26",
            "local_date": "2026-07-28",
            "weekday": "tuesday",
            "public_execution_allowed": False,
        }
        with tempfile.TemporaryDirectory() as directory, patch.object(
            autonomous_content_run, "selected_topic", return_value=(2, "נושא")
        ), patch.object(
            autonomous_content_run,
            "generate_article",
            return_value=("כותרת", "# כותרת\n\nתוכן"),
        ) as generate, patch.object(
            autonomous_content_run,
            "save_draft",
            return_value=Path(directory) / "draft.md",
        ):
            result = autonomous_content_run.generate_job(
                job,
                datetime(2026, 7, 28, 6, 0, tzinfo=timezone.utc),
                Path(directory),
            )
        self.assertEqual(result["destination_site_key"], "DRGUYROFE_COM")
        self.assertEqual(result["content_stream"], "evergreen_knowledge")
        self.assertIn(
            "לא תגובה לחדשות",
            generate.call_args.kwargs["editorial_context"],
        )

    def test_media_archive_is_event_driven_and_needs_a_real_transcript(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory)
            (media / "media-transcript-1.json").write_text(
                json.dumps(
                    {
                        "status": "transcript_ready_for_editorial_review",
                        "destination_site_key": "GUYROFE_WIX_MEDIA_ARCHIVE",
                        "source_media_url": "https://open.spotify.com/episode/real",
                        "source_media_type": "podcast",
                        "platform_urls": {
                            "spotify": "https://open.spotify.com/episode/real",
                            "apple_podcasts": "https://podcasts.apple.com/il/podcast/show/id1?i=2",
                        },
                        "working_title": "פרק בדיקה",
                        "transcript_markdown": "# פרק בדיקה\n\nתמליל מקורי",
                        "created_at": "2026-07-29T05:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            job = {
                "stream": "media_archive",
                "site_key": "GUYROFE_WIX_MEDIA_ARCHIVE",
                "channels": [],
                "week": "event-2026-07-29",
                "local_date": "2026-07-29",
                "weekday": "event_driven",
                "public_execution_allowed": False,
            }
            with patch.object(
                autonomous_content_run,
                "save_draft",
                return_value=media / "draft.md",
            ) as save:
                result = autonomous_content_run.generate_job(
                    job,
                    datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc),
                    media,
                    {"generated": []},
                    media_brief_dir=media,
                )
        self.assertEqual(
            result["source_media_url"],
            "https://open.spotify.com/episode/real",
        )
        saved_content = save.call_args.args[3]
        self.assertIn("האזנה ב‑Spotify", saved_content)
        self.assertIn("האזנה ב‑Apple Podcasts", saved_content)
        self.assertEqual(
            save.call_args.kwargs["metadata"]["content_stream"],
            "media_archive",
        )

    def test_unbundled_generated_draft_is_retried_without_regeneration(self):
        with tempfile.TemporaryDirectory(
            dir=autonomous_content_run.ROOT
        ) as directory:
            root = Path(directory)
            draft = root / "draft.md"
            draft.write_text("# טיוטה\n", encoding="utf-8")
            state = {
                "generated": [{
                    "stream": "canonical_depth",
                    "site_key": "GUYROFE_COM",
                    "channels": ["facebook", "linkedin"],
                    "draft_path": draft.relative_to(
                        autonomous_content_run.ROOT
                    ).as_posix(),
                }]
            }
            approval_index = root / "approval-index.json"
            approval_index.write_text(
                json.dumps({"bundles": []}),
                encoding="utf-8",
            )
            jobs = autonomous_content_run.unbundled_generated_jobs(
                state,
                approval_index,
            )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(
            jobs[0]["status"],
            "existing_draft_ready_for_bundle_retry",
        )
        self.assertFalse(jobs[0]["public_execution_allowed"])


if __name__ == "__main__":
    unittest.main()
