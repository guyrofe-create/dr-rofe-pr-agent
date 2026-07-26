import unittest
import sys
from types import SimpleNamespace
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
