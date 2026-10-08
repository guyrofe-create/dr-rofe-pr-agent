import unittest
from datetime import date
from unittest.mock import Mock

from scripts.reputation_core.search_console import fetch_search_console_appearance_rows


class SearchConsoleAppearanceTests(unittest.TestCase):
    def test_collects_and_marks_generative_ai_appearances(self):
        session = Mock()
        response = Mock(status_code=200)
        response.raise_for_status.return_value = None
        response.json.return_value = {"rows": [{
            "keys": ["AI_OVERVIEW", "https://example.com/article"],
            "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 3.5,
        }]}
        session.post.return_value = response
        rows = fetch_search_console_appearance_rows(
            "token", ["sc-domain:example.com"], end_date=date(2026, 10, 5), session=session,
        )
        self.assertEqual(rows[0]["search_appearance"], "AI_OVERVIEW")
        self.assertTrue(rows[0]["is_generative_ai"])
        self.assertEqual(session.post.call_args.kwargs["json"]["dimensions"], ["searchAppearance", "page"])


if __name__ == "__main__":
    unittest.main()
