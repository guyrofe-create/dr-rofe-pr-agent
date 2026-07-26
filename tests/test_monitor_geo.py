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

    @patch("scripts.monitor_run.requests.get")
    def test_missing_facebook_review_permission_is_a_clear_skip(self, get):
        response = Mock()
        response.status_code = 400
        response.json.return_value = {"error": {"code": 283}}
        get.return_value = response
        old_value = monitor_run.REPORT["facebook_recommendations"]
        try:
            with patch.dict(
                os.environ,
                {"FACEBOOK_PAGE_ID": "1", "FACEBOOK_PAGE_TOKEN": "token"},
                clear=True,
            ):
                monitor_run.check_facebook_recommendations()
                result = monitor_run.REPORT["facebook_recommendations"]
        finally:
            monitor_run.REPORT["facebook_recommendations"] = old_value
        self.assertEqual(result["status"], "skipped_missing_permission")

    def test_serp_checks_run_only_once_per_day(self):
        with patch.object(
            monitor_run,
            "HISTORY",
            {"last_serp_check_date": "2026-07-26"},
        ):
            self.assertFalse(monitor_run.serp_checks_due("2026-07-26"))
            self.assertTrue(monitor_run.serp_checks_due("2026-07-27"))


if __name__ == "__main__":
    unittest.main()
