import json
import tempfile
import unittest
from pathlib import Path

from scripts.reputation_core.content_routing import (
    assert_cross_domain_original,
    content_fingerprint,
    draft_metadata,
    validate_stream_destination,
)


class ContentRoutingTests(unittest.TestCase):
    def test_metadata_and_stream_destination_are_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            draft = Path(directory) / "draft.md"
            draft.write_text(
                '<!--\ncontent_stream: "evergreen_knowledge"\n'
                'destination_site_key: "DRGUYROFE_COM"\n-->\n\n# כותרת\n',
                encoding="utf-8",
            )
            metadata = draft_metadata(draft)
        validate_stream_destination(
            site_key=metadata["destination_site_key"],
            stream=metadata["content_stream"],
            metadata=metadata,
        )

    def test_wrong_owned_domain_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "belongs on DRGUYROFE_COM"):
            validate_stream_destination(
                site_key="GUYROFE_COM",
                stream="evergreen_knowledge",
            )

    def test_media_archive_requires_real_media_and_clean_audit(self):
        with self.assertRaisesRegex(ValueError, "original podcast or video"):
            validate_stream_destination(
                site_key="GUYROFE_WIX_MEDIA_ARCHIVE",
                stream="media_archive",
                metadata={"legacy_content_audit_passed": True},
            )
        with self.assertRaisesRegex(PermissionError, "legacy-content audit"):
            validate_stream_destination(
                site_key="GUYROFE_WIX_MEDIA_ARCHIVE",
                stream="media_archive",
                metadata={"source_media_url": "https://youtube.com/watch?v=1"},
            )

    def test_exact_cross_domain_duplicate_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "current.md"
            other = root / "other.md"
            text = "# בדיקה\n\nזהו תוכן רפואי מקורי " * 20
            current.write_text(text, encoding="utf-8")
            other.write_text(text, encoding="utf-8")
            index = root / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "drafts": [
                            {
                                "path": "other.md",
                                "destination_site_key": "GUYROFE_COM",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Exact cross-domain duplicate"):
                assert_cross_domain_original(
                    content=text,
                    site_key="DRGUYROFE_COM",
                    draft_path=current,
                    draft_index_path=index,
                    project_root=root,
                )

    def test_fingerprint_ignores_links_but_not_article_substance(self):
        left = "# כותרת\n\nמידע חשוב [במקור](https://example.com/a)"
        right = "# כותרת\n\nמידע חשוב [במקור](https://example.org/b)"
        self.assertEqual(content_fingerprint(left), content_fingerprint(right))


if __name__ == "__main__":
    unittest.main()
