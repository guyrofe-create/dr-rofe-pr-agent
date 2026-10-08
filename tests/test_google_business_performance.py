import unittest
from datetime import date
from unittest.mock import Mock

from scripts.reputation_core.google_business_performance import (
    fetch_google_business_performance,
    fetch_google_business_profile_details,
    summarize_google_business_performance,
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
        self.assertIn("summary", result)

    def test_summary_proves_visibility_without_conflating_organic_rank(self):
        summary = summarize_google_business_performance([{
            "dailyMetricTimeSeries": [
                {"dailyMetric": "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "timeSeries": {"datedValues": [{"value": "1427"}]}},
                {"dailyMetric": "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "timeSeries": {"datedValues": [{"value": "81"}]}},
                {"dailyMetric": "WEBSITE_CLICKS", "timeSeries": {"datedValues": [{"value": "14"}]}},
            ]
        }], [])
        self.assertEqual(summary["visibility_status"], "visible_in_google_search_or_maps")
        self.assertEqual(summary["total_impressions"], 1508)
        self.assertFalse(summary["local_rank_weak"])
        self.assertEqual(summary["organic_page_one_status"], "not_measured_by_google_business_api")
        self.assertEqual(summary["keyword_data_status"], "not_returned_by_api")

    def test_zero_impressions_is_a_real_local_visibility_alert(self):
        summary = summarize_google_business_performance([], [])
        self.assertTrue(summary["local_rank_weak"])
        self.assertEqual(summary["visibility_status"], "no_measured_visibility")

    def test_reads_profile_details_without_mutation(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"name": "locations/34", "title": "Example"}
        session = Mock()
        session.get.return_value = response
        result = fetch_google_business_profile_details(
            "token", "accounts/12/locations/34", session=session
        )
        self.assertEqual(result["name"], "locations/34")
        self.assertIn("categories", session.get.call_args.kwargs["params"]["readMask"])
        self.assertFalse(session.post.called)

if __name__ == "__main__":
    unittest.main()
