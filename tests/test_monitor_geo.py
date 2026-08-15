import unittest
import sys
import os
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch.dict(
    sys.modules,
    {"openai": SimpleNamespace(OpenAI=object)},
):
    from scripts import monitor_run


class MonitorGeoTests(unittest.TestCase):
    def test_normalized_host_skips_unconfigured_asset_urls(self):
        self.assertEqual(monitor_run.normalized_host(None), "")
        self.assertEqual(monitor_run.normalized_host(b"https://example.com"), "")
        self.assertEqual(
            monitor_run.normalized_host(" https://www.guyrofe.com/profile "),
            "guyrofe.com",
        )

    def test_geo_prompts_measure_identity_assets_and_current_status(self):
        prompts = "\n".join(monitor_run.GEO_PROMPTS)
        self.assertIn("מי הוא", prompts)
        self.assertIn("ספרים", prompts)
        self.assertIn("פודקאסט", prompts)
        self.assertIn("מקבל כיום מטופלות", prompts)
        self.assertNotIn("המלץ על גינקולוג", prompts)

    def test_rank_keywords_do_not_target_active_clinical_services(self):
        keywords = "\n".join(monitor_run.KEYWORDS)
        self.assertNotIn("גינקולוג תל אביב", keywords)
        self.assertNotIn("לפרוסקופיה גינקולוגית", keywords)

    def test_negated_current_practice_status_is_not_flagged(self):
        self.assertFalse(
            monitor_run.has_active_practice_claim(
                "לפי האתר הרשמי, ד״ר גיא רופא אינו מקבל מטופלות כעת."
            )
        )

    def test_affirmative_current_practice_status_is_flagged(self):
        self.assertTrue(
            monitor_run.has_active_practice_claim(
                "ד״ר גיא רופא מקבל מטופלות וניתן לפנות לקביעת תור."
            )
        )
        self.assertTrue(
            monitor_run.has_active_practice_claim(
                "ד״ר גיא רופא משמש כרופא בכיר במרכז רפואי."
            )
        )

    def test_uncertain_status_is_not_treated_as_affirmative(self):
        self.assertFalse(
            monitor_run.has_active_practice_claim(
                "אין לי את המידע המעודכן לגבי קבלת מטופלות או לקביעת תורים."
            )
        )

    def test_clinic_recommendation_is_still_flagged(self):
        self.assertTrue(
            monitor_run.has_active_practice_claim(
                "אין לי מידע על תורים. מומלץ ליצור קשר עם המרפאה שלו."
            )
        )

    def test_named_clinic_recommendation_is_flagged(self):
        self.assertTrue(
            monitor_run.has_active_practice_claim(
                "אין לי מידע עדכני. מומלץ ליצור קשר עם המרפאה של ד״ר גיא רופא."
            )
        )

    def test_uncertainty_does_not_hide_same_sentence_clinic_recommendation(self):
        self.assertTrue(
            monitor_run.has_active_practice_claim(
                "אין לי מידע עדכני ולכן מומלץ ליצור קשר עם המרפאה שלו."
            )
        )

    def test_negated_status_does_not_hide_a_separate_affirmative_claim(self):
        self.assertTrue(
            monitor_run.has_active_practice_claim(
                "הוא אינו מקבל מטופלות, אך מפעיל מרפאה פרטית."
            )
        )

    def test_known_wrong_identity_is_flagged(self):
        self.assertTrue(
            monitor_run.has_identity_misinformation(
                "ד״ר גיא רופא מומחה לגידול עצי פרי ולהשבחת זנים."
            )
        )

    def test_live_wrong_identity_variants_are_flagged(self):
        wrong_answers = (
            "ד״ר גיא רופא הוא אורתופד המתמחה בכירורגיה של הברך.",
            "ד״ר גיא רופא הוא אישיות פיקטיבית.",
            "ד״ר גיא רופא הוא חוקר בתחום ההיסטוריה.",
            "הוא חוקר ומרצה בנושאי תרבות איטלקית ותולדות האמנות.",
            "ספרו הידוע הוא הכתובת של רבקה.",
            "למיטב ידיעתי הוא לא פרסם ספרים.",
        )
        for answer in wrong_answers:
            with self.subTest(answer=answer):
                self.assertTrue(
                    monitor_run.has_identity_misinformation(answer)
                )

    def test_correct_podcast_existence_is_not_flagged(self):
        self.assertFalse(
            monitor_run.has_identity_misinformation(
                "לד״ר גיא רופא יש פודקאסט בשם רפואה על כוס קפה."
            )
        )

    def test_public_identity_non_answer_is_a_knowledge_gap(self):
        self.assertTrue(
            monitor_run.has_ai_knowledge_gap(
                "מהם הנכסים הרשמיים של ד״ר גיא רופא ברשת?",
                "איני יכול לספק מידע. מומלץ לחפש בגוגל.",
            )
        )

    def test_patient_availability_uncertainty_is_not_a_knowledge_gap(self):
        self.assertFalse(
            monitor_run.has_ai_knowledge_gap(
                "האם ד״ר גיא רופא מקבל כיום מטופלות או מזמין לקביעת תור?",
                "אין לי מידע עדכני לגבי זמינות.",
            )
        )

    def test_ai_alert_markdown_contains_prompt_and_excerpt(self):
        old_alerts = monitor_run.REPORT["alerts"]
        monitor_run.REPORT["alerts"] = [{
            "type": "ai_identity_misinformation",
            "prompt": "מי הוא ד״ר גיא רופא?",
            "excerpt": "תשובה שגויה",
        }]
        try:
            rendered = monitor_run.format_alert_markdown()
        finally:
            monitor_run.REPORT["alerts"] = old_alerts
        self.assertIn("מי הוא ד״ר גיא רופא?", rendered)
        self.assertIn("תשובה שגויה", rendered)

    def test_safe_error_redacts_named_and_generic_tokens(self):
        with patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "123:secret"},
            clear=True,
        ):
            rendered = monitor_run.safe_error(
                "https://api.telegram.org/bot123:secret/getMe token=abcS123 next"
            )
        self.assertNotIn("123:secret", rendered)
        self.assertNotIn("abcS123", rendered)
        self.assertIn("token=[REDACTED]", rendered)

    def test_configured_token_failure_degrades_monitor(self):
        old_tokens = monitor_run.REPORT["tokens"]
        monitor_run.REPORT["tokens"] = [{
            "platform": "Pinterest",
            "configured": True,
            "ok": False,
            "detail": "expired",
        }]
        try:
            with patch.dict(os.environ, {}, clear=True):
                failures = monitor_run.critical_monitor_failures()
        finally:
            monitor_run.REPORT["tokens"] = old_tokens
        self.assertIn("publisher credentials: Pinterest", failures)

    def test_missing_facebook_review_permission_is_a_clear_skip(self):
        response = Mock()
        response.status_code = 400
        response.json.return_value = {"error": {"code": 283}}
        old_value = monitor_run.REPORT["facebook_recommendations"]
        try:
            with patch.object(
                monitor_run.requests,
                "get",
                return_value=response,
            ), patch.dict(
                os.environ,
                {"FACEBOOK_PAGE_ID": "1", "FACEBOOK_PAGE_TOKEN": "token"},
                clear=True,
            ):
                monitor_run.check_facebook_recommendations()
                result = monitor_run.REPORT["facebook_recommendations"]
        finally:
            monitor_run.REPORT["facebook_recommendations"] = old_value
        self.assertEqual(result["status"], "skipped_missing_permission")

    def test_serp_checks_run_only_on_twice_monthly_dates(self):
        with patch.object(
            monitor_run,
            "HISTORY",
            {"last_serp_check_date": "2026-07-01"},
        ):
            self.assertFalse(monitor_run.serp_checks_due("2026-07-01"))
            self.assertFalse(monitor_run.serp_checks_due("2026-07-02"))
            self.assertTrue(monitor_run.serp_checks_due("2026-07-15"))

    def test_manual_serp_check_can_override_calendar(self):
        with patch.object(monitor_run, "HISTORY", {}), patch.dict(
            os.environ,
            {"FORCE_SERP_CHECK": "true"},
            clear=True,
        ):
            self.assertTrue(monitor_run.serp_checks_due("2026-07-02"))

    def test_free_serp_plan_uses_two_core_queries_on_regular_day(self):
        plan = monitor_run.serp_run_plan("2026-07-27")
        self.assertEqual(plan["mode"], "daily_core")
        self.assertEqual(
            plan["queries"],
            ["ד״ר גיא רופא", "גיא רופא"],
        )
        self.assertEqual(plan["engines"], ["google"])
        self.assertEqual(plan["devices"], ["mobile"])
        self.assertFalse(plan["web_mentions"])

    def test_free_serp_plan_runs_full_matrix_on_sunday(self):
        plan = monitor_run.serp_run_plan("2026-08-02")
        self.assertEqual(plan["mode"], "extended_weekly")
        self.assertEqual(len(plan["queries"]), 4)
        self.assertEqual(plan["engines"], ["google", "bing"])
        self.assertEqual(plan["devices"], ["mobile", "desktop"])
        self.assertFalse(plan["web_mentions"])

    def test_serp_budget_stops_before_provider_free_limit(self):
        with patch.object(
            monitor_run,
            "HISTORY",
            {"serp_usage_by_month": {"2026-07": 220}},
        ):
            self.assertFalse(monitor_run.serp_budget_available("2026-07-31"))
            self.assertFalse(monitor_run.serp_checks_due("2026-07-31"))
            self.assertTrue(monitor_run.serp_budget_available("2026-08-01"))

    def test_serp_result_cache_prevents_duplicate_provider_request(self):
        cached = {
            "engine": "google",
            "keyword": "ד״ר גיא רופא",
            "device": "mobile",
            "status": "found",
            "results": [],
        }
        with patch.object(
            monitor_run,
            "HISTORY",
            {
                "serp_result_cache": {
                    "2026-07-27": {
                        monitor_run.serp_cache_key(
                            "google",
                            "ד״ר גיא רופא",
                            "mobile",
                        ): cached,
                    },
                },
            },
        ):
            self.assertEqual(
                monitor_run.cached_serp_result(
                    "2026-07-27",
                    "google",
                    "ד״ר גיא רופא",
                    "mobile",
                ),
                cached,
            )

    def test_serp_pagination_normalizes_absolute_positions(self):
        self.assertEqual(
            monitor_run._absolute_organic_results(
                [{"position": 1, "link": "https://example.com/deep"}],
                100,
            )[0]["position"],
            101,
        )
        self.assertEqual(
            monitor_run._next_serp_start(
                {
                    "serpapi_pagination": {
                        "next": "https://serpapi.com/search.json?q=brand&start=200",
                    },
                },
                100,
                100,
            ),
            200,
        )

    def test_failed_serp_snapshot_remains_retryable(self):
        with patch.object(
            monitor_run,
            "HISTORY",
            {
                "snapshots": [{
                    "date": "2026-07-15T10:00:00",
                    "rank": [{"status": "error", "detail": "429"}],
                }],
            },
        ):
            self.assertTrue(monitor_run.serp_checks_due("2026-07-15"))

    def test_serp_quota_backoff_stops_same_day_retry_storm(self):
        with patch.object(
            monitor_run,
            "HISTORY",
            {"serp_retry_on_date": "2026-07-16"},
        ):
            self.assertFalse(monitor_run.serp_checks_due("2026-07-15"))
            self.assertTrue(monitor_run.serp_checks_due("2026-08-01"))

    def test_active_serp_backoff_does_not_repeat_failure_email(self):
        old_rank = monitor_run.REPORT["rank"]
        monitor_run.REPORT["rank"] = [{
            "status": "skipped",
            "reason": "SerpApi retry backoff is active",
        }]
        try:
            with patch.object(
                monitor_run,
                "HISTORY",
                {"serp_retry_on_date": "2999-01-02"},
            ), patch.dict(
                os.environ,
                {"SERPAPI_KEY": "configured"},
                clear=True,
            ):
                self.assertNotIn(
                    "SERP rank: no complete fresh measurement",
                    monitor_run.critical_monitor_failures(),
                )
        finally:
            monitor_run.REPORT["rank"] = old_rank

    def test_serp_safety_budget_is_degraded_but_not_a_failed_run(self):
        old_rank = monitor_run.REPORT["rank"]
        monitor_run.REPORT["rank"] = [{
            "status": "skipped",
            "reason": "configured monthly SerpApi safety budget reached",
        }]
        try:
            with patch.object(
                monitor_run,
                "HISTORY",
                {},
            ), patch.dict(
                os.environ,
                {"SERPAPI_KEY": "configured"},
                clear=True,
            ):
                self.assertEqual(monitor_run.critical_monitor_failures(), [])
                self.assertIn(
                    "SERP rank: configured monthly SerpApi safety budget reached",
                    monitor_run.monitor_degradations(),
                )
        finally:
            monitor_run.REPORT["rank"] = old_rank

    def test_serp_query_error_still_fails_the_monitor(self):
        old_rank = monitor_run.REPORT["rank"]
        monitor_run.REPORT["rank"] = [{
            "status": "error",
            "detail": "unexpected provider response",
        }]
        try:
            with patch.dict(
                os.environ,
                {"SERPAPI_KEY": "configured"},
                clear=True,
            ):
                self.assertIn(
                    "SERP rank: 1 query errors",
                    monitor_run.critical_monitor_failures(),
                )
        finally:
            monitor_run.REPORT["rank"] = old_rank

    def test_activate_serp_backoff_retries_next_calendar_day(self):
        with patch.object(monitor_run, "HISTORY", {}):
            monitor_run.activate_serp_backoff("2026-07-26")
            self.assertEqual(
                monitor_run.HISTORY["serp_retry_on_date"],
                "2026-07-27",
            )

    def test_ai_repeated_sampling_runs_twice_monthly(self):
        with patch.object(
            monitor_run,
            "HISTORY",
            {"last_ai_check_date": "2026-07-01"},
        ):
            self.assertFalse(monitor_run.ai_checks_due("2026-07-01"))
            self.assertFalse(monitor_run.ai_checks_due("2026-07-02"))
            self.assertTrue(monitor_run.ai_checks_due("2026-07-15"))

    def test_ai_manual_check_can_override_calendar(self):
        with patch.object(monitor_run, "HISTORY", {}), patch.dict(
            os.environ,
            {"FORCE_AI_CHECK": "true"},
            clear=True,
        ):
            self.assertTrue(monitor_run.ai_checks_due("2026-07-02"))

    def test_search_console_maintenance_runs_twice_monthly(self):
        with patch.object(monitor_run, "HISTORY", {}):
            self.assertTrue(monitor_run.scheduled_maintenance_due(
                "last_search_console_check_date",
                "search_console_check_days_of_month",
                "2026-07-01",
                default_days=[1, 15],
                force_environment_key="FORCE_SEARCH_CONSOLE_CHECK",
            ))
            self.assertFalse(monitor_run.scheduled_maintenance_due(
                "last_search_console_check_date",
                "search_console_check_days_of_month",
                "2026-07-02",
                default_days=[1, 15],
                force_environment_key="FORCE_SEARCH_CONSOLE_CHECK",
            ))


if __name__ == "__main__":
    unittest.main()
