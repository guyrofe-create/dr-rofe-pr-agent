import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.reputation_core.bing_ai_performance import (
    import_bing_ai_performance,
)
from scripts.reputation_core.measurement import (
    add_serp_volatility,
    measure_ai_surfaces,
    measure_serp_surface,
    summarize_bing_ai_performance,
)


class SerpMeasurementTests(unittest.TestCase):
    def test_ai_measurement_plan_covers_major_answer_surfaces(self):
        config = json.loads(Path("config/serp_targets.json").read_text(encoding="utf-8"))
        surfaces = {
            (item["engine"], item["surface"])
            for item in config["measurement_plan"]["ai_surfaces"]
        }
        self.assertTrue({
            ("OpenAI", "chatgpt_search"),
            ("Google", "ai_overviews"),
            ("Google", "gemini"),
            ("Perplexity", "answer_engine"),
            ("Anthropic", "claude_web_search"),
            ("Bing", "ai_performance"),
        }.issubset(surfaces))

    def sample(self, observed_at, results):
        return {
            "engine": "google",
            "surface": "web_search",
            "interface": "search_data_api",
            "collection_method": "serpapi",
            "query": "Example Person",
            "country": "IL",
            "language": "he",
            "device": "mobile",
            "observed_at": observed_at,
            "features": {
                "knowledge_panel": True,
                "images": True,
                "video": False,
            },
            "results": results,
        }

    def test_serp_counts_weights_negative_exposure_and_features(self):
        sample = self.sample("2026-07-26T08:00:00Z", [])
        control = {
            "results": [
                {
                    "position": 1, "url": "https://owned.test",
                    "controlled": True, "desired": True,
                    "sentiment": "positive",
                },
                {
                    "position": 2, "url": "https://good.test",
                    "controlled": False, "desired": True,
                    "sentiment": "positive",
                },
                {
                    "position": 3, "url": "https://bad.test",
                    "controlled": False, "desired": False,
                    "sentiment": "negative",
                },
            ]
        }
        measured = measure_serp_surface(control, sample)
        self.assertEqual(measured["controlled_count_top10"], 1)
        self.assertEqual(measured["desired_count_top10"], 2)
        self.assertEqual(measured["weighted_desired_score"], 1.5)
        self.assertEqual(measured["weighted_negative_exposure"], 0.3333)
        self.assertEqual(measured["negative_positions"], [3])
        self.assertTrue(measured["features"]["knowledge_panel"])
        self.assertEqual(measured["feature_count"], 2)

    def test_volatility_is_7_and_28_days_and_never_blends_devices(self):
        old = measure_serp_surface(
            {"results": [{
                "position": 8, "url": "https://owned.test",
                "controlled": True, "desired": True,
            }]},
            self.sample("2026-07-20T08:00:00Z", []),
        )
        current = measure_serp_surface(
            {"results": [{
                "position": 2, "url": "https://owned.test",
                "controlled": True, "desired": True,
            }]},
            self.sample("2026-07-26T08:00:00Z", []),
        )
        desktop = {
            **old, "device": "desktop",
            "observed_at": "2026-07-25T08:00:00Z",
        }
        report = add_serp_volatility(
            [current], [old, desktop],
            as_of=datetime(2026, 7, 26, tzinfo=timezone.utc),
        )[0]
        self.assertEqual(
            report["volatility"]["7d"]["mean_absolute_position_change"], 6
        )
        self.assertEqual(report["volatility"]["7d"]["samples"], 2)
        self.assertEqual(report["volatility"]["28d"]["samples"], 2)


class AiMeasurementTests(unittest.TestCase):
    def test_ai_metrics_and_api_consumer_surfaces_are_not_blended(self):
        base = {
            "engine": "OpenAI",
            "model": "example-model",
            "country": "IL",
            "language": "he",
            "prompt": "מי הוא Example Person?",
            "fact_evaluation": {"status": "pass"},
            "mentions_dr_rofe": True,
            "cited_sources": ["https://approved.test/profile"],
            "exact_answer": "Example Person הוא מחבר ומקור רשמי",
        }
        api_samples = [
            {
                **base, "sample": 1, "surface": "responses_web_search",
                "interface": "api",
                "collection_method": "openai_responses_api",
            },
            {
                **base, "sample": 2, "surface": "responses_web_search",
                "interface": "api",
                "collection_method": "openai_responses_api",
            },
        ]
        consumer = {
            **base, "surface": "chatgpt_search",
            "interface": "consumer_ui",
            "collection_method": "authorized_browser_sample",
            "fact_evaluation": {"status": "fail"},
            "identity_misinformation": True,
            "cited_sources": ["https://bad.test/story"],
        }
        reports = measure_ai_surfaces(
            api_samples + [consumer],
            {"approved.test"},
            ["מחבר ומקור רשמי"],
        )
        self.assertEqual(len(reports), 2)
        api = next(item for item in reports if item["interface"] == "api")
        ui = next(
            item for item in reports if item["interface"] == "consumer_ui"
        )
        self.assertEqual(api["identity_accuracy_rate"], 1.0)
        self.assertEqual(api["factual_accuracy_rate"], 1.0)
        self.assertEqual(api["approved_source_citation_rate"], 1.0)
        self.assertEqual(api["source_diversity"]["unique_hosts"], 1)
        self.assertEqual(api["harmful_or_incorrect_rate"], 0.0)
        self.assertEqual(api["cross_sample_stability"], 1.0)
        self.assertEqual(ui["identity_accuracy_rate"], 0.0)
        self.assertEqual(ui["harmful_or_incorrect_rate"], 1.0)

    def test_unknown_fact_accuracy_fails_closed(self):
        reports = measure_ai_surfaces([{
            "engine": "Example",
            "surface": "consumer",
            "interface": "consumer_ui",
            "collection_method": "authorized_browser_sample",
            "model": "unknown",
            "country": "IL",
            "language": "he",
            "prompt": "who",
            "exact_answer": "an unevaluated answer",
            "identity_correct": True,
            "cited_sources": [],
        }], set())
        self.assertEqual(reports[0]["factual_accuracy_rate"], 0.0)


class BingAiPerformanceTests(unittest.TestCase):
    def test_csv_import_and_summary_preserve_ui_export_provenance(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "bing.csv"
            path.write_text(
                "date,cited page,grounding query,citation count,"
                "citation share\n"
                "2026-07-01,https://example.test/a,query one,3,25%\n"
                "2026-07-02,https://example.test/b,query two,2,10%\n",
                encoding="utf-8",
            )
            dataset = import_bing_ai_performance(path)
        summary = summarize_bing_ai_performance(dataset)
        self.assertEqual(dataset["collection_method"], "authorized_manual_export")
        self.assertEqual(summary["interface"], "bing_webmaster_tools_consumer_ui")
        self.assertEqual(summary["total_citations"], 5)
        self.assertEqual(summary["unique_cited_pages"], 2)
        self.assertEqual(summary["unique_grounding_queries"], 2)
        self.assertNotIn("api", summary["collection_method"])

    def test_json_import_accepts_documented_canonical_fields(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "bing.json"
            path.write_text(json.dumps([{
                "date": "2026-07-01",
                "cited_url": "https://example.test/a",
                "grounding_query": "query",
                "citations": 4,
            }]), encoding="utf-8")
            dataset = import_bing_ai_performance(path)
        self.assertEqual(dataset["rows"][0]["citations"], 4)


if __name__ == "__main__":
    unittest.main()
