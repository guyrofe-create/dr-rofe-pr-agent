import unittest

from scripts.check_asset_reachability import audit_html


class AssetReachabilityAuditTests(unittest.TestCase):
    def test_extracts_entity_and_technical_seo_signals(self):
        report = audit_html(
            """
            <html><head>
              <title>ד״ר גיא רופא — ספרים ופודקאסט</title>
              <meta name="description" content="עמוד המחבר הרשמי">
              <link rel="canonical" href="/author/guy-rofe">
              <script type="application/ld+json">{"@type":"ProfilePage"}</script>
            </head><body><h1>גיא רופא</h1>
              <a href="https://guyrofe.com/">האתר הרשמי</a>
            </body></html>
            """,
            "https://books.example/author/guy-rofe",
        )
        self.assertTrue(report["entity_in_title"])
        self.assertTrue(report["entity_in_page"])
        self.assertTrue(report["official_link_present"])
        self.assertEqual(report["canonical"], "https://books.example/author/guy-rofe")
        self.assertEqual(report["schema_types"], ["ProfilePage"])
        self.assertEqual(report["seo_issues"], [])

    def test_flags_noindex_and_missing_entity(self):
        report = audit_html(
            '<html><head><title>Generic</title><meta name="robots" content="noindex"></head><body></body></html>',
            "https://example.com/profile",
        )
        self.assertTrue(report["noindex"])
        self.assertIn("missing_entity_name", report["seo_issues"])
        self.assertIn("missing_canonical", report["seo_issues"])


if __name__ == "__main__":
    unittest.main()
