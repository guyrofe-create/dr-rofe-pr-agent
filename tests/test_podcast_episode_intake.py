import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.podcast_episode_intake import create_episode_brief


class PodcastEpisodeIntakeTests(unittest.TestCase):
    def test_creates_review_only_brief_with_both_platform_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "podcasts.json"
            config.write_text(
                json.dumps({"shows": [{
                    "key": "REFUA_AL_KOS_CAFE",
                    "title": "רפואה על כוס קפה",
                    "creator": "ד״ר גיא רופא",
                    "destination_site_key": "GUYROFE_WIX_MEDIA_ARCHIVE",
                    "content_stream": "media_archive",
                }]}),
                encoding="utf-8",
            )
            path = create_episode_brief(
                title="פרק חדש",
                transcript_markdown="# פרק חדש\n\nתמליל מאומת",
                spotify_url="https://open.spotify.com/episode/abc",
                apple_url="https://podcasts.apple.com/il/podcast/show/id1?i=2",
                config_path=config,
                output_dir=root / "media",
                now=datetime(2026, 7, 30, tzinfo=timezone.utc),
            )
            brief = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(brief["status"], "transcript_ready_for_editorial_review")
        self.assertEqual(brief["source_media_type"], "podcast")
        self.assertIn("spotify", brief["platform_urls"])
        self.assertIn("apple_podcasts", brief["platform_urls"])
        self.assertFalse(brief["public_execution_allowed"])

