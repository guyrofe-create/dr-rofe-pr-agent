import unittest
from datetime import date
from unittest.mock import Mock

from scripts.reputation_core.google_business_performance import (
    fetch_google_business_performance,
)


class GoogleBusinessPerformanceTests(unittest.TestCase):
    def test_collects_daily_metrics_and_monthly_keywords(self):
        daily = Mock()
        daily.raise_for_status.return_value = None
        daily.json.return_value = {
            "multiDailyMetricTimeSeries": [{"dailyMetric": "WEBSITE_CLICKS"}]
        }
        keywords = Mock()
        keywords.raise_for_status.return_value = None
        keywords.json.return_value = {
            "searchKeywordsCounts": [{"searchKeyword": "גיא רופא"}]
        }
        session = Mock()
        session.get.side_effect = [daily, keywords]

        result = fetch_google_business_performance(
            "token",
            "accounts/12/locations/34",
            end_date=date(2026, 9, 28),
            session=session,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["location"], "locations/34")
        self.assertEqual(result["period"]["start"], "2026-09-01")
        self.assertEqual(len(result["daily_metrics"]), 1)
        self.assertEqual(len(result["monthly_search_keywords"]), 1)
        self.assertIn("fetchMultiDailyMetricsTimeSeries", session.get.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
