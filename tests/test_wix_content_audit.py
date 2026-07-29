import unittest

from scripts.wix_content_audit import classify_urls


class WixContentAuditTests(unittest.TestCase):
    def test_legacy_and_service_pages_are_publication_blockers(self):
        result = classify_urls(
            [
                "https://example.com/copy-of-old",
                "https://example.com/blank-10",
                "https://example.com/service-page/medical-advice",
                "https://example.com/post/valid",
            ]
        )
        self.assertEqual(len(result["legacy_or_placeholder_urls"]), 2)
        self.assertEqual(
            len(result["service_or_booking_urls_requiring_factual_review"]),
            1,
        )


if __name__ == "__main__":
    unittest.main()
