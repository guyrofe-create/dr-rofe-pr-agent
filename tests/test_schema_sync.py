import json
import unittest

from scripts.schema_sync import build_llms_txt, build_schema


class NeutralEntitySchemaTests(unittest.TestCase):
    def setUp(self):
        with open("data/business_profile.json", encoding="utf-8") as handle:
            self.profile = json.load(handle)

    def test_schema_is_person_not_active_medical_business(self):
        schema = build_schema(self.profile)
        serialized = json.dumps(schema, ensure_ascii=False)
        self.assertEqual(schema["@type"], "Person")
        self.assertNotIn("MedicalBusiness", serialized)
        self.assertNotIn("Physician", serialized)
        self.assertNotIn("openingHoursSpecification", schema)
        self.assertNotIn("address", schema)
        self.assertNotIn("telephone", schema)
        self.assertNotIn("aggregateRating", schema)

    def test_llms_text_states_non_practicing_status(self):
        text = build_llms_txt(self.profile)
        self.assertIn("not currently practicing medicine", text)
        self.assertIn("not accepting patients", text)
        self.assertNotIn("Services: fertility treatment", text)


if __name__ == "__main__":
    unittest.main()
