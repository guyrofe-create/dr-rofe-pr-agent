import json
import unittest

from scripts.fix_duplicate_breadcrumb import (
    ARTICLE_ID,
    BREADCRUMB_ID,
    remove_agent_breadcrumb,
)


class DuplicateBreadcrumbRepairTests(unittest.TestCase):
    def test_removes_only_agent_breadcrumb_and_reference(self):
        payload = {
            "@context": "https://schema.org",
            "@graph": [
                {"@type": "Article", "@id": ARTICLE_ID,
                 "breadcrumb": {"@id": BREADCRUMB_ID}},
                {"@type": "BreadcrumbList", "@id": BREADCRUMB_ID,
                 "itemListElement": []},
                {"@type": "ImageObject", "@id": "image"},
            ],
        }
        visible = "<h1>כותרת</h1><p>תוכן רפואי.</p>"
        html = visible + '<script type="application/ld+json">' + json.dumps(payload) + "</script>"
        updated, changed = remove_agent_breadcrumb(html)
        self.assertEqual(changed, 1)
        self.assertIn(visible, updated)
        self.assertNotIn('"@type":"BreadcrumbList"', updated)
        self.assertNotIn('"breadcrumb"', updated)
        self.assertIn('"@type":"ImageObject"', updated)

    def test_ignores_unrelated_json_ld(self):
        html = '<script type="application/ld+json">{"@type":"Person"}</script>'
        self.assertEqual(remove_agent_breadcrumb(html), (html, 0))


if __name__ == "__main__":
    unittest.main()
