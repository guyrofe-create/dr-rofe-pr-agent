import json
import unittest
from unittest.mock import Mock, patch

from scripts.schema_sync import (
    build_llms_txt,
    build_schema,
    wp_find_or_create_page,
    wp_update_page,
)


class NeutralEntitySchemaTests(unittest.TestCase):
    def setUp(self):
        with open("data/business_profile.json", encoding="utf-8") as handle:
            self.profile = json.load(handle)

    def test_schema_is_person_not_active_medical_business(self):
        schema = build_schema(self.profile)
        serialized = json.dumps(schema, ensure_ascii=False)
        graph = schema["@graph"]
        self.assertEqual(graph[0]["@type"], "ProfilePage")
        person = next(item for item in graph if item["@type"] == "Person")
        self.assertEqual(person["mainEntityOfPage"]["@id"], graph[0]["@id"])
        self.assertEqual(graph[0]["mainEntity"]["@id"], person["@id"])
        self.assertNotIn("MedicalBusiness", serialized)
        self.assertNotIn("Physician", serialized)
        self.assertNotIn("openingHoursSpecification", serialized)
        self.assertNotIn('"address"', serialized)
        self.assertNotIn("telephone", serialized)
        self.assertNotIn("aggregateRating", serialized)

    def test_llms_text_states_non_practicing_status(self):
        text = build_llms_txt(self.profile)
        self.assertIn("not currently practicing medicine", text)
        self.assertIn("not accepting patients", text)
        self.assertNotIn("Services: fertility treatment", text)

    @patch("scripts.schema_sync.requests.get")
    def test_page_lookup_uses_public_status_without_draft_filter(self, get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{"id": 7}]
        get.return_value = response

        page_id = wp_find_or_create_page(
            "https://example.com", ("user", "password"), "profile", "Profile"
        )

        self.assertEqual(page_id, 7)
        self.assertEqual(
            get.call_args.kwargs["params"],
            {"slug": "profile", "status": "publish"},
        )

    @patch("scripts.schema_sync.requests.post")
    def test_existing_page_title_is_updated_with_content(self, post):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"id": 7}
        post.return_value = response
        wp_update_page(
            "https://example.com",
            ("user", "password"),
            7,
            "<script>schema</script>",
            title="Schema Markup — Person / Medical Content Creator",
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["title"],
            "Schema Markup — Person / Medical Content Creator",
        )


if __name__ == "__main__":
    unittest.main()
