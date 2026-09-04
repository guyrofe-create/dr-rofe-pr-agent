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
    render_profile_page,
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
from scripts.reputation_core.publication_seo import (
    audit_published_html,
    build_search_target,
    render_related_links_html,
    select_related_publications,
    unbranded_title,
    urls_equivalent,
    wordpress_public_slug,
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

    def test_profile_page_uses_descriptive_linkedin_anchor(self):
        html = render_profile_page(self.profile)
        self.assertIn(
            '<a rel="me" href="https://www.linkedin.com/in/guyrofe">'
            "ד״ר גיא רופא בלינקדאין</a>",
            html,
        )

    def test_verified_credentials_are_emitted_when_present(self):
        profile = {
            **self.profile,
            "hasCredential": [{
                "@type": "Credential",
                "name": "Verified credential",
                "recognizedBy": {
                    "@type": "Organization",
                    "name": "Verified authority",
                },
                "evidence": [{"url": "https://authority.example/credential"}],
            }],
        }
        person = build_profile_page_schema(profile)["@graph"][1]
        self.assertEqual(person["hasCredential"][0]["@type"], "Credential")
        self.assertNotIn("evidence", person["hasCredential"][0])

    def test_unverified_credentials_are_not_emitted(self):
        profile = {
            **self.profile,
            "hasCredential": [{
                "@type": "Credential",
                "name": "Unverified credential",
            }],
        }
        person = build_profile_page_schema(profile)["@graph"][1]
        self.assertNotIn("hasCredential", person)

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
        self.assertGreater(
            contracted.index("## על המחבר"), contracted.index("## מקורות")
        )

    def test_article_contract_replaces_model_byline_and_requires_real_body_mention(self):
        profile = load_client_profile()
        contracted = apply_article_contract(
            "# כותרת\n\n"
            "[מאת ד״ר גיא רופא](https://guyrofe.com)\n\n"
            "תוכן עובדתי ללא אזכור בגוף.\n\n"
            "## מקורות\n\nhttps://www.who.int/a",
            profile,
        )
        report = audit_article_entity_contract(contracted, profile)

        self.assertTrue(report.passed, report.errors)
        self.assertEqual(contracted.count("מאת [ד״ר גיא רופא]"), 1)
        self.assertNotIn("[מאת ד״ר גיא רופא]", contracted)
        self.assertIn("מאגר המידע של ד״ר גיא רופא", contracted)
        self.assertLess(
            contracted.index("תוכן עובדתי ללא אזכור בגוף."),
            contracted.index("מאגר המידע של ד״ר גיא רופא"),
        )

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

    def test_meta_description_ends_cleanly_instead_of_mid_sentence(self):
        profile = load_client_profile()
        description = meta_description(
            "# כותרת | ד״ר גיא רופא\n\n"
            "מאת [ד״ר גיא רופא](https://guyrofe.com/profile/)\n\n"
            "זהו משפט ראשון קצר וברור. זהו משפט שני ארוך מאוד שנועד "
            "להמחיש שתיאור התוצאה אינו אמור להיחתך באמצע מילה או משפט.",
            profile,
            max_length=65,
        )
        self.assertTrue(description.endswith("."), description)
        self.assertLessEqual(len(description), 65)

    def test_meta_description_skips_legacy_byline_and_never_uses_ellipsis(self):
        profile = load_client_profile()
        description = meta_description(
            "# כותרת | ד״ר גיא רופא\n\n"
            "מאת: [ד״ר גיא רופא — הפרופיל הרשמי](https://guyrofe.com)\n\n"
            "**התשובה הקצרה:** מחקר רחב מצא קשר אפשרי בין המשתנים, "
            "אך הוא אינו מוכיח סיבתיות ולכן נדרש פירוש זהיר של התוצאות "
            "לפני קבלת החלטה רפואית אישית.",
            profile,
            max_length=100,
        )
        self.assertNotIn("מאת", description)
        self.assertNotIn("http", description)
        self.assertNotIn("…", description)
        self.assertTrue(description.endswith("."), description)
        self.assertEqual(description.count("ד״ר גיא רופא"), 1)
        self.assertLessEqual(len(description), 100)

    def test_meta_description_prefers_later_complete_sentence_to_broken_fragment(self):
        profile = load_client_profile()
        description = meta_description(
            "# כותרת | ד״ר גיא רופא\n\n"
            "זהו משפט ראשון ארוך מאוד הכולל פרטים רבים על אוכלוסיית המחקר "
            "ועל כל המשתנים שנבדקו לאורך שנים רבות ולכן אינו מתאים לתיאור קצר. "
            "הממצא מעניין, אך אינו מוכיח סיבתיות.",
            profile,
            max_length=70,
        )
        self.assertEqual(
            description,
            "ד״ר גיא רופא: הממצא מעניין, אך אינו מוכיח סיבתיות.",
        )

    def test_publication_seo_builds_one_brand_suffix_and_topic_query_map(self):
        title = "גיל המעבר: תסמינים וטיפול | ד״ר גיא רופא"
        self.assertEqual(
            unbranded_title(title), "גיל המעבר: תסמינים וטיפול"
        )
        target = build_search_target(
            title,
            metadata={"content_stream": "canonical_depth"},
        )
        self.assertEqual(target["primary_query"], "גיל המעבר: תסמינים וטיפול")
        self.assertEqual(target["entity_queries"], ["ד״ר גיא רופא", "גיא רופא"])
        self.assertIn("ד״ר גיא רופא", target["secondary_queries"][0])

    def test_wordpress_slug_stays_below_encoded_provider_limit(self):
        title = (
            "בדיקת דם העלתה חשד לסרטן ובצילום התגלה ממצא אחר לחלוטין "
            "שדורש בירור רפואי נוסף ומעקב מסודר"
        )
        slug = wordpress_public_slug(title)
        from urllib.parse import quote

        self.assertLessEqual(len(quote(slug, safe="-")), 180)
        self.assertFalse(slug.endswith("-"))
        self.assertTrue(title.startswith(slug.replace("-", " ")))
        self.assertEqual(
            wordpress_public_slug("מיץ גזר, ג'ינג'ר ורימון", encoded_limit=80),
            "מיץ-גזר-גינגר",
        )

    def test_url_equivalence_accepts_unicode_and_percent_encoded_paths(self):
        self.assertTrue(urls_equivalent(
            "https://www.drguyrofe.co.il/%D7%9B%D7%95%D7%AA%D7%A8%D7%AA/",
            "https://drguyrofe.co.il/כותרת",
        ))
        self.assertFalse(urls_equivalent(
            "https://drguyrofe.co.il/כותרת-א/",
            "https://drguyrofe.co.il/כותרת-ב/",
        ))
        self.assertFalse(urls_equivalent(
            "https://guyrofe.com/?p=1",
            "https://guyrofe.com/?p=2",
        ))
        self.assertTrue(urls_equivalent(
            "https://guyrofe.com/page/?b=2&a=1",
            "https://www.guyrofe.com/page?a=1&b=2",
        ))

    def test_related_publications_are_same_host_relevant_and_crawlable(self):
        campaigns = [{
            "title": "גיל המעבר ותסמינים | ד״ר גיא רופא",
            "destinations": [{
                "status": "published",
                "url": "https://guyrofe.com/menopause-symptoms/",
            }],
        }, {
            "title": "כאבי אגן כרוניים | ד״ר גיא רופא",
            "destinations": [{
                "status": "published",
                "url": "https://other.example/pelvic-pain/",
            }],
        }]
        links = select_related_publications(
            "טיפול בתסמיני גיל המעבר | ד״ר גיא רופא",
            "https://guyrofe.com/menopause-treatment/",
            campaigns,
        )
        self.assertEqual(len(links), 1)
        rendered = render_related_links_html(links)
        self.assertIn('<a href="https://guyrofe.com/menopause-symptoms/">', rendered)

    def test_served_page_audit_detects_duplicate_brand_and_internal_slug(self):
        document = """<html><head>
        <title>גיל המעבר | ד״ר גיא רופא - ד״ר גיא רופא</title>
        <meta name="description" content="תיאור מלא וברור.">
        <link rel="canonical" href="https://guyrofe.com/pilot-run-12/">
        </head><body><script>https://guyrofe.com/#person</script></body></html>"""
        report = audit_published_html(
            document,
            expected_url="https://guyrofe.com/pilot-run-12/",
            canonical_name="ד״ר גיא רופא",
        )
        self.assertFalse(report["passed"])
        self.assertFalse(report["checks"]["brand_once_in_title"])
        self.assertFalse(report["checks"]["no_internal_run_slug"])

    def test_served_page_audit_accepts_encoded_canonical_equivalence(self):
        document = """<html><head>
        <title>שחלות פוליציסטיות | ד״ר גיא רופא</title>
        <meta name="description" content="תיאור מלא וברור.">
        <link rel="canonical" href="https://guyrofe.com/תסמונת-השחלות/">
        </head><body><script>https://guyrofe.com/#person</script></body></html>"""
        report = audit_published_html(
            document,
            expected_url="https://guyrofe.com/%D7%AA%D7%A1%D7%9E%D7%95%D7%A0%D7%AA-%D7%94%D7%A9%D7%97%D7%9C%D7%95%D7%AA/",
            canonical_name="ד״ר גיא רופא",
        )
        self.assertTrue(report["checks"]["canonical_matches"])

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
