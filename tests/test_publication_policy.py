import unittest

from scripts.publication_policy import enforce_channel_policy, enforce_publication_policy


class PublicationPolicyTests(unittest.TestCase):
    def test_allows_information_only_cta(self):
        text = "מידע כללי לציבור.\n\nלמידע נוסף: https://guyrofe.com"
        self.assertEqual(enforce_publication_policy(text), text)

    def test_rejects_consultation_invitation(self):
        with self.assertRaises(ValueError):
            enforce_publication_policy("לקביעת תור צרו קשר")

    def test_rejects_active_practice_claim(self):
        with self.assertRaises(ValueError):
            enforce_publication_policy("במרפאה שלי אני מטפל במקרים מורכבים")

    def test_rejects_third_person_active_practice_claims(self):
        prohibited = (
            "ד״ר גיא רופא מקבל כיום מטופלות",
            "ד״ר גיא רופא מפעיל מרפאה",
            "ד״ר גיא רופא מעניק טיפול",
            "ד״ר גיא רופא זמין לקביעת תורים",
        )
        for text in prohibited:
            with self.subTest(text=text), self.assertRaises(ValueError):
                enforce_publication_policy(text)

    def test_allows_accurate_non_practicing_disclosure(self):
        text = (
            "ד״ר גיא רופא אינו מקבל כיום מטופלות ואינו זמין לקביעת תורים."
        )
        self.assertEqual(enforce_publication_policy(text), text)

    def test_rejects_english_solicitation(self):
        with self.assertRaises(ValueError):
            enforce_publication_policy("Book an appointment today")

    def test_owner_managed_and_disabled_channels_are_blocked(self):
        for channel in (
            "TikTok",
            "X",
            "Telegram",
            "Tumblr",
            "Google Business Profile",
        ):
            with self.subTest(channel=channel), self.assertRaises(ValueError):
                enforce_channel_policy(channel)

    def test_product_managed_channels_are_allowed(self):
        for channel in ("Facebook", "Instagram", "LinkedIn", "Pinterest"):
            with self.subTest(channel=channel):
                self.assertEqual(enforce_channel_policy(channel), channel)


if __name__ == "__main__":
    unittest.main()
