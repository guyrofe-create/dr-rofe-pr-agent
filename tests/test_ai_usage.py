import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from scripts.reputation_core.ai_usage import (
    load_usage_events,
    record_ai_usage,
)


class AiUsageTests(unittest.TestCase):
    def test_records_tokens_search_calls_and_cost_without_content(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(
                input_tokens=1000,
                input_tokens_details=SimpleNamespace(
                    cached_tokens=200,
                    cache_write_tokens=0,
                ),
                output_tokens=500,
                output_tokens_details=SimpleNamespace(reasoning_tokens=120),
            ),
            output=[
                SimpleNamespace(type="web_search_call"),
                SimpleNamespace(type="message"),
            ],
        )
        occurred_at = datetime(2026, 7, 29, 10, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            event = record_ai_usage(
                response,
                operation="article_generation",
                model="gpt-5.6",
                usage_dir=tmp,
                occurred_at=occurred_at,
            )
            stored = json.loads(next(Path(tmp).glob("*.json")).read_text())
            loaded = load_usage_events(
                occurred_at,
                occurred_at.replace(hour=11),
                usage_dir=tmp,
            )
        self.assertEqual(event["web_search_calls"], 1)
        self.assertEqual(event["reasoning_tokens"], 120)
        self.assertAlmostEqual(event["estimated_cost_usd"], 0.0291)
        self.assertEqual(stored, event)
        self.assertEqual(loaded, [event])
        self.assertNotIn("prompt", json.dumps(event))
        self.assertNotIn("output_text", json.dumps(event))

    def test_unknown_model_keeps_usage_but_marks_cost_unknown(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            output=[],
        )
        with tempfile.TemporaryDirectory() as tmp:
            event = record_ai_usage(
                response,
                operation="test",
                model="future-model",
                usage_dir=tmp,
            )
        self.assertEqual(event["input_tokens"], 10)
        self.assertIsNone(event["estimated_cost_usd"])


if __name__ == "__main__":
    unittest.main()
