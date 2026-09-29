import json
import tempfile
import unittest
from pathlib import Path

from scripts.reputation_core.content_routing import (
    assert_cross_domain_original,
    content_fingerprint,
    draft_metadata,
    topic_is_duplicate,
    semantic_topic_analysis,
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
            with self.assertRaisesRegex(ValueError, "already used|Exact duplicate"):
                assert_cross_domain_original(
                    content=text,
                    site_key="DRGUYROFE_COM",
                    draft_path=current,
                    draft_index_path=index,
                    project_root=root,
                )

    def test_same_domain_topic_reuse_is_rejected_even_with_new_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            drafts = root / "content_drafts"
            drafts.mkdir()
            current = drafts / "current.md"
            other = drafts / "other.md"
            current.write_text(
                '<!--\ntopic: "כאבים בזמן הווסת"\n-->'
                "\n\n# כאבי מחזור: מדריך חדש\n\nטקסט חדש לחלוטין",
                encoding="utf-8",
            )
            other.write_text(
                '<!--\ntopic: "כאבים בזמן הווסת"\n-->'
                "\n\n# שאלות על כאבי מחזור\n\nתוכן ישן ושונה",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Editorial topic was already used"):
                assert_cross_domain_original(
                    content=current.read_text(encoding="utf-8"),
                    site_key="GUYROFE_COM",
                    draft_path=current,
                    draft_index_path=drafts / "missing-index.json",
                    project_root=root,
                )

    def test_topic_match_tolerates_light_rewording(self):
        self.assertTrue(
            topic_is_duplicate(
                "כאבים חזקים בזמן הווסת",
                "כאבים בזמן הווסת: מתי לפנות לבדיקה",
            )
        )

    def test_medical_synonyms_are_semantic_duplicates(self):
        report = semantic_topic_analysis(
            "דיסמנוריאה: תסמינים ואבחון",
            "כאבי מחזור: איך מאבחנים את הבעיה",
        )
        self.assertTrue(report["duplicate"])
        self.assertIn("menstrual_pain", report["shared_medical_concepts"])

    def test_same_condition_with_distinct_reader_intent_is_allowed(self):
        self.assertFalse(topic_is_duplicate(
            "אנדומטריוזיס: תסמינים",
            "אנדומטריוזיס: אפשרויות טיפול",
        ))

    def test_fingerprint_ignores_links_but_not_article_substance(self):
        left = "# כותרת\n\nמידע חשוב [במקור](https://example.com/a)"
        right = "# כותרת\n\nמידע חשוב [במקור](https://example.org/b)"
        self.assertEqual(content_fingerprint(left), content_fingerprint(right))


if __name__ == "__main__":
    unittest.main()
