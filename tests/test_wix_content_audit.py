import hashlib
import unittest

from scripts.wix_content_audit import classify_urls, _substantive_title


class WixContentAuditTests(unittest.TestCase):
    def test_substantive_legacy_slugs_are_advisory_not_blockers(self):
        legacy_url = "https://example.com/copy-of-old"
        service_url = "https://example.com/service-page/medical-advice"
        title = "ייעוץ רפואי"
        description = "תיאור עובדתי שנבדק"
        fingerprint = hashlib.sha256(
            f"{title}\n{description}".encode("utf-8")
        ).hexdigest()
        result = classify_urls(
            [
                legacy_url,
                "https://example.com/blank-10",
                service_url,
                "https://example.com/post/valid",
            ],
            metadata_by_url={
                legacy_url: {"title": "שחלות פוליציסטיות | homepage"},
                "https://example.com/blank-10": {"title": "Blank | homepage"},
                service_url: {
                    "title": title,
                    "description": description,
                    "metadata_sha256": fingerprint,
                },
            },
            reviewed_service_metadata={service_url: fingerprint},
        )
        self.assertEqual(len(result["legacy_slug_urls"]), 2)
        self.assertEqual(
            result["legacy_or_placeholder_urls"],
            ["https://example.com/blank-10"],
        )
        self.assertEqual(len(result["service_or_booking_urls"]), 1)
        self.assertEqual(
            len(result["service_or_booking_urls_requiring_factual_review"]),
            0,
        )

    def test_changed_service_metadata_requires_new_review(self):
        url = "https://example.com/service-page/medical-advice"
        result = classify_urls(
            [url],
            metadata_by_url={
                url: {
                    "title": "ייעוץ",
                    "metadata_sha256": "new-content",
                }
            },
            reviewed_service_metadata={url: "reviewed-content"},
        )
        self.assertEqual(
            result["service_or_booking_urls_requiring_factual_review"],
            [url],
        )

    def test_substantive_title_detection(self):
        self.assertTrue(_substantive_title("פטריה נרתיקית | homepage"))
        self.assertFalse(_substantive_title("Blank | homepage"))


if __name__ == "__main__":
    unittest.main()
