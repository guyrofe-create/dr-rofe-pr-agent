import json
import unittest

from scripts.reputation_core.crawler_policy import (
    audit_robots_text,
    recommended_robots_block,
)
from scripts.reputation_core.entity_seo import (
    audit_article_markdown,
    build_article_schema,
    build_profile_page_schema,
    json_ld_script,
    validate_media_metadata,
)
from scripts.reputation_core.entity_contract import (
    apply_article_contract,
    audit_article_entity_contract,
    build_entity_context,
    meta_description,
    title_with_entity,
)
from scripts.reputation_core.strategy import load_client_profile
from scripts.reputation_core.platform_content import (
    build_platform_variants,
    variants_are_distinct,
)


class EntitySeoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open("data/business_profile.json", encoding="utf-8") as handle:
            cls.profile = json.load(handle)

    def test_profile_page_and_person_have_stable_linked_ids(self):
        schema = build_profile_page_schema(self.profile)
        page, person = schema["@graph"]
        self.assertEqual(page["@type"], "ProfilePage")
        self.assertEqual(person["@type"], "Person")
        self.assertEqual(page["mainEntity"]["@id"], person["@id"])
        self.assertEqual(person["mainEntityOfPage"]["@id"], page["@id"])
        self.assertTrue(person["sameAs"])

    def test_article_links_author_to_profile_and_citations(self):
        schema = build_article_schema(
            self.profile,
            headline="כותרת",
            article_url="https://guyrofe.com/article/",
            description="תיאור",
            citations=["https://who.int/a", "https://who.int/a"],
        )
        self.assertEqual(schema["author"]["@id"], "https://guyrofe.com/#person")
        self.assertEqual(schema["author"]["url"], "https://guyrofe.com/profile/")
        self.assertEqual(schema["citation"], ["https://who.int/a"])
        rendered = json_ld_script(schema)
        self.assertIn('type="application/ld+json"', rendered)
        self.assertIn('"Article"', rendered)

    def test_article_quality_is_answer_first_and_conditional_faq(self):
        good = """# כותרת

זו תשובה ישירה וברורה לשאלה המרכזית, לפני ההרחבה המקצועית.

## הסבר

פירוט.

## מקורות

https://www.who.int/a
https://pubmed.ncbi.nlm.nih.gov/1/
"""
        report = audit_article_markdown(good)
        self.assertTrue(report.passed, report.warnings)

        bad_faq = good + "\n## שאלות נפוצות\n\nטקסט ללא שאלות ממשיות."
        report = audit_article_markdown(bad_faq)
        self.assertFalse(report.checks["faq_valid_when_present"])

    def test_media_requires_truthful_description_and_video_transcript(self):
        self.assertEqual(
            validate_media_metadata(
                {
                    "type": "image",
                    "alt_text": "איור מופשט",
                    "visual_description": "איור מופשט כחול",
                    "entity_named": False,
                    "entity_relevant": False,
                }
            ),
            [],
        )
        self.assertIn(
            "video_transcript_required",
            validate_media_metadata(
                {"type": "video", "captions": "captions", "transcript": ""}
            ),
        )

    def test_platform_variants_are_native_and_fact_bounded(self):
        variants = build_platform_variants(
            "כותרת",
            "# כותרת\n\nמשפט פתיחה שמסביר היטב את הנושא לקוראים. "
            "משפט נוסף שמספק מידע מאושר בלבד. עוד משפט שימושי לקורא.",
            "https://guyrofe.com/a",
        )
        self.assertTrue(variants_are_distinct(variants))
        self.assertIn("•", variants["linkedin"])
        self.assertIsInstance(variants["pinterest"], dict)
        self.assertIn("<h2>", variants["blogger"])
        for platform in ("facebook", "linkedin"):
            self.assertEqual(variants[platform].count("ד״ר גיא רופא"), 1)
        self.assertIn("ד״ר גיא רופא", variants["pinterest"]["title"])

    def test_article_contract_binds_title_byline_author_box_and_profile(self):
        profile = load_client_profile()
        contracted = apply_article_contract(
            "# כותרת נושאית\n\nתשובה ישירה ושימושית לקוראים.\n\n"
            "## הסבר\n\nפירוט.\n\n## מקורות\n\nhttps://www.who.int/a",
            profile,
        )
        report = audit_article_entity_contract(contracted, profile)
        self.assertTrue(report.passed, report.errors)
        self.assertIn("# כותרת נושאית | ד״ר גיא רופא", contracted)
        self.assertIn("מאת [ד״ר גיא רופא]", contracted)
        self.assertIn("## על המחבר", contracted)
        self.assertLess(contracted.index("## על המחבר"), contracted.index("## מקורות"))

    def test_title_and_meta_description_use_name_once(self):
        profile = load_client_profile()
        context = build_entity_context(profile)
        title = title_with_entity("מידע רפואי | ד\"ר גיא רופא", context)
        self.assertEqual(title, "מידע רפואי | ד״ר גיא רופא")
        description = meta_description(
            "# מידע רפואי | ד״ר גיא רופא\n\n"
            "מאת [ד״ר גיא רופא](https://guyrofe.com/profile/)\n\n"
            "תשובה ישירה לקוראים.",
            profile,
        )
        self.assertEqual(description.count("ד״ר גיא רופא"), 1)

    def test_search_crawlers_are_audited_separately(self):
        robots = """User-agent: *
Allow: /

User-agent: OAI-SearchBot
Disallow: /

User-agent: PerplexityBot
Allow: /
"""
        checks = {item.user_agent: item for item in audit_robots_text(robots, "https://x.test")}
        self.assertFalse(checks["OAI-SearchBot"].allowed)
        self.assertTrue(checks["PerplexityBot"].allowed)
        self.assertIn("does not guarantee", recommended_robots_block())


if __name__ == "__main__":
    unittest.main()
