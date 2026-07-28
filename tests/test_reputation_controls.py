import hashlib
import unittest

from scripts.reputation_core.crawler_policy import (
    CRAWLER_ROLES,
    audit_robots_text,
    recommended_robots_block,
)
from scripts.reputation_core.reputation_controls import (
    audit_backlinks,
    build_ai_feedback_task,
    build_disavow_proposal,
    build_knowledge_panel_task,
    build_review_request_campaign,
    build_wikimedia_workstream,
    validate_legal_evidence_chain,
)


class ReputationControlsTests(unittest.TestCase):
    def test_crawler_audit_separates_search_training_and_user_fetch(self):
        checks = audit_robots_text("User-agent: *\nAllow: /\n", "https://example.com")
        agents = {item.user_agent for item in checks}
        self.assertEqual(agents, set(CRAWLER_ROLES))
        self.assertIn("GPTBot", agents)
        self.assertIn("ChatGPT-User", agents)
        self.assertIn("Claude-SearchBot", agents)
        self.assertIn("Google-Extended", agents)
        self.assertTrue(all(item.role for item in checks))
        recommended = recommended_robots_block()
        self.assertIn("OAI-SearchBot", recommended)
        self.assertNotIn("GPTBot", recommended)
        self.assertNotIn("Google-Extended", recommended)

    def test_backlinks_are_monitored_but_never_auto_disavowed(self):
        audit = audit_backlinks([{
            "source_url": "https://spam.example/a",
            "target_url": "https://guyrofe.com/",
            "risk_signals": ["paid_link_network"],
        }])
        self.assertEqual(len(audit["manual_review_candidates"]), 1)
        self.assertFalse(audit["disavow_submission_allowed"])
        proposal = build_disavow_proposal(audit, ["spam.example"])
        self.assertEqual(proposal["status"], "awaiting_explicit_approval")
        self.assertFalse(proposal["auto_submit"])

    def test_review_campaign_rejects_sentiment_gating(self):
        with self.assertRaises(ValueError):
            build_review_request_campaign(
                [{"id": "1", "nps": 10, "real_interaction_verified": True,
                  "contact_permission": True}],
                destination_url="https://example.com/review",
                message="Please leave an honest review.",
            )
        campaign = build_review_request_campaign(
            [{"id": "1", "real_interaction_verified": True,
              "contact_permission": True, "opted_out": False}],
            destination_url="https://example.com/review",
            message="Please leave an honest review, positive or negative.",
        )
        self.assertEqual(campaign["recipient_ids"], ["1"])
        self.assertTrue(campaign["requires_external_outreach_approval"])
        self.assertFalse(campaign["auto_send"])

    def test_legal_action_requires_verified_chain_and_matching_hash(self):
        document = b"verified court record"
        record = {
            "case_number": "123-45",
            "court": "Example Court",
            "document_url": "https://court.example/record",
            "document_sha256": hashlib.sha256(document).hexdigest(),
            "retrieved_at": "2026-07-28T10:00:00Z",
            "verified_at": "2026-07-28T10:05:00Z",
            "verified_by": "legal-owner",
            "verification_source_url": "https://court.example/case/123-45",
            "court_record_verified": True,
        }
        result = validate_legal_evidence_chain(record, document_bytes=document)
        self.assertTrue(result["ready"])
        self.assertFalse(result["legal_request_allowed"])
        broken = validate_legal_evidence_chain(record, document_bytes=b"other")
        self.assertFalse(broken["ready"])

    def test_knowledge_and_feedback_tasks_are_manual_and_evidenced(self):
        panel = build_knowledge_panel_task({"name": "ד״ר גיא רופא"})
        self.assertFalse(panel["auto_claim"])
        feedback = build_ai_feedback_task({
            "engine": "Gemini",
            "prompt": "Who is Dr Guy Rofe?",
            "exact_answer": "Wrong answer",
            "observed_at": "2026-07-28T10:00:00Z",
            "error": "identity mismatch",
        })
        self.assertEqual(feedback["status"], "ready_for_manual_submission")
        self.assertEqual(feedback["cost"], 0)
        self.assertFalse(feedback["auto_submit"])

    def test_wikimedia_is_not_treated_as_a_controlled_asset(self):
        workstream = build_wikimedia_workstream({"name": "ד״ר גיא רופא"})
        self.assertFalse(workstream["direct_edit_authorized"])
        self.assertFalse(workstream["new_page_authorized"])
        self.assertEqual(
            workstream["preferred_action"],
            "propose_changes_on_talk_page_or_requested_edit",
        )


if __name__ == "__main__":
    unittest.main()
