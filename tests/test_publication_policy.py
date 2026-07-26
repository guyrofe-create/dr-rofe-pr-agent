import unittest

from scripts.publication_policy import enforce_publication_policy


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

    def test_rejects_english_solicitation(self):
        with self.assertRaises(ValueError):
            enforce_publication_policy("Book an appointment today")


if __name__ == "__main__":
    unittest.main()
