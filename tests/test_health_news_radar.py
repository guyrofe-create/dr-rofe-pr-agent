import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.health_news_radar import enrich_candidate, parse_feed, run
from scripts.reputation_core.editorial_radar import rank_news_candidates


NOW = datetime(2026, 7, 29, 6, 0, tzinfo=timezone.utc)


class HealthNewsRadarTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "id": "test_health",
            "name": "חדשות בריאות",
            "allowed_hosts": ["news.example"],
        }

    def test_parses_metadata_and_removes_tracking_parameters(self):
        feed = """<rss><channel><item>
          <title>מחקר חדש על בריאות נשים</title>
          <link>https://news.example/story?utm_source=rss&amp;id=7</link>
          <description><![CDATA[<b>תקציר רפואי</b>]]></description>
          <pubDate>Wed, 29 Jul 2026 05:00:00 +0000</pubDate>
        </item></channel></rss>"""
        items = parse_feed(feed, self.source, NOW)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://news.example/story?id=7")
        self.assertEqual(items[0]["summary"], "תקציר רפואי")
        self.assertEqual(items[0]["feed_position"], 1)

    def test_rejects_links_outside_the_source_allowlist(self):
        feed = """<rss><channel><item>
          <title>מחקר חדש על בריאות נשים</title>
          <link>https://tracker.example/story</link>
        </item></channel></rss>"""
        self.assertEqual(parse_feed(feed, self.source, NOW), [])

    def test_marks_sponsored_content_as_prohibited(self):
        candidate = {
            "title": "תוכן ממומן: טיפול חדש",
            "summary": "כתבת בריאות",
            "source_id": "test_health",
        }
        enriched = enrich_candidate(candidate, ["תוכן ממומן"], set())
        self.assertTrue(enriched["prohibited"])

    def test_client_topic_relevance_prioritizes_womens_health(self):
        focused = enrich_candidate({
            "title": "מחקר חדש על אנדומטריוזיס ופוריות",
            "summary": "מידע רפואי לנשים",
            "source_id": "test_health",
        }, [], set())
        generic = enrich_candidate({
            "title": "מחקר חדש על דמנציה",
            "summary": "מידע רפואי כללי",
            "source_id": "test_health",
        }, [], set())
        self.assertGreater(focused["client_topic_relevance"], 0)
        self.assertEqual(generic["client_topic_relevance"], 0)

    def test_soft_source_cooldown_breaks_a_close_score_tie(self):
        common = {
            "published_at": NOW.isoformat(),
            "source_kind": "major_news",
            "attention_score": 3,
            "public_health_relevance": 4,
            "analysis_gap": 2,
            "sensationalism_risk": 0,
        }
        ranked = rank_news_candidates([
            {
                **common,
                "title": "כתבה ממקור שנבחר לאחרונה",
                "url": "https://one.example/story",
                "source_id": "recent",
                "source_diversity_penalty": 5,
            },
            {
                **common,
                "title": "כתבה ממקור חלופי",
                "url": "https://two.example/story",
                "source_id": "fresh",
                "source_diversity_penalty": 0,
            },
        ], now=NOW)
        self.assertEqual(ranked[0]["source_id"], "fresh")

    def test_run_creates_review_only_brief_for_drguyrofe(self):
        feed = """<rss><channel><item>
          <title>מחקר חדש: טיפול רפואי לנשים מפחית סיכון ב-30 אחוז</title>
          <link>https://news.example/story</link>
          <description>מחקר בריאות רפואי חדש על טיפול בנשים ועל סיכון למחלה</description>
          <pubDate>Wed, 29 Jul 2026 05:00:00 +0000</pubDate>
        </item></channel></rss>"""
        config = {
            "destination_site_key": "DRGUYROFE_CO_IL",
            "destination_url": "https://www.drguyrofe.co.il",
            "selection": {
                "max_age_hours": 72,
                "candidate_limit_per_source": 20,
                "source_cooldown_days": 5,
                "source_diversity_penalty": 5,
                "minimum_opportunity_score": 25,
            },
            "sources": [{**self.source, "feed_url": "https://feed.example/rss", "enabled": True}],
            "blocked_markers": ["תוכן ממומן"],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            state_path = root / "state.json"
            brief_dir = root / "briefs"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            state = run(config_path, state_path, brief_dir, NOW, fetcher=lambda source: feed)
            brief = json.loads(next(brief_dir.glob("health-news-*.json")).read_text(encoding="utf-8"))

        self.assertEqual(state["selected"]["source_id"], "test_health")
        self.assertEqual(brief["destination_site_key"], "DRGUYROFE_CO_IL")
        self.assertEqual(brief["analyzed_news_url"], "https://news.example/story")
        self.assertTrue(brief["requires_primary_source_research"])
        self.assertEqual(brief["minimum_additional_authoritative_sources"], 2)
        self.assertFalse(brief["public_execution_allowed"])
        self.assertFalse(brief["article_body_copied"])

    def test_previously_selected_article_is_not_selected_again(self):
        feed = """<rss><channel><item>
          <title>מחקר חדש: טיפול רפואי לנשים מפחית סיכון ב-30 אחוז</title>
          <link>https://news.example/story</link>
          <description>מחקר בריאות רפואי חדש על טיפול בנשים ועל סיכון למחלה</description>
          <pubDate>Wed, 29 Jul 2026 05:00:00 +0000</pubDate>
        </item></channel></rss>"""
        config = {
            "destination_site_key": "DRGUYROFE_CO_IL",
            "destination_url": "https://www.drguyrofe.co.il",
            "selection": {
                "max_age_hours": 72,
                "candidate_limit_per_source": 20,
                "source_cooldown_days": 5,
                "source_diversity_penalty": 5,
                "minimum_opportunity_score": 25,
            },
            "sources": [{**self.source, "feed_url": "https://feed.example/rss", "enabled": True}],
            "blocked_markers": ["תוכן ממומן"],
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "config.json"
            state_path = root / "state.json"
            brief_dir = root / "briefs"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            first = run(config_path, state_path, brief_dir, NOW, fetcher=lambda source: feed)
            second = run(config_path, state_path, brief_dir, NOW, fetcher=lambda source: feed)

        self.assertIsNotNone(first["selected"])
        self.assertIsNone(second["selected"])
        self.assertEqual(len(second["selection_history"]), 1)


if __name__ == "__main__":
    unittest.main()
