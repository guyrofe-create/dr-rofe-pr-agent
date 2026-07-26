import copy
import tempfile
import unittest
from pathlib import Path

from scripts.reputation_core.approval_workflow import (
    ExecutionLedger,
    ReconciliationRequired,
    approve_bundle,
    build_bundle,
    render_preview,
    verify_approval,
)


SECRET = "a-test-signing-secret-with-32-characters"


def sample_bundle():
    return build_bundle(
        action_type="public_post",
        objective="Build accurate visibility",
        query="Example Person",
        targets=[
            {
                "target_id": "linkedin",
                "platform": "LinkedIn",
                "asset": "member profile",
                "payload": {"text": "Exact approved text"},
            }
        ],
        sources=[{"url": "https://example.com/source"}],
        media={
            "uri": "media/image.png",
            "sha256": "abc",
            "alt_text": "Accurate visual description",
        },
        risk={"level": "medium", "score": 5, "notes": ["medical"]},
        compliance={"reviewed": True},
        sensitive_actions=["medical_content"],
    )


class ApprovalWorkflowTests(unittest.TestCase):
    def test_every_material_edit_invalidates_approval(self):
        bundle = sample_bundle()
        record = approve_bundle(
            bundle,
            approved_by="owner",
            approved_scopes=["public_publication", "medical_content"],
            signing_secret=SECRET,
        )
        verify_approval(bundle, record, SECRET)
        for change in ("text", "alt", "target", "source", "risk"):
            altered = copy.deepcopy(bundle)
            if change == "text":
                altered["targets"][0]["payload"]["text"] += " changed"
            elif change == "alt":
                altered["media"]["alt_text"] += " changed"
            elif change == "target":
                altered["targets"][0]["asset"] = "other profile"
            elif change == "source":
                altered["sources"].append("https://example.com/other")
            else:
                altered["risk"]["score"] = 6
            with self.assertRaisesRegex(ValueError, "changed|invalid"):
                verify_approval(altered, record, SECRET)

    def test_sensitive_scopes_must_each_be_explicit(self):
        bundle = sample_bundle()
        with self.assertRaisesRegex(PermissionError, "medical_content"):
            approve_bundle(
                bundle,
                approved_by="owner",
                approved_scopes=["public_publication"],
                signing_secret=SECRET,
            )

    def test_tampered_signature_is_rejected(self):
        bundle = sample_bundle()
        record = approve_bundle(
            bundle,
            approved_by="owner",
            approved_scopes=["public_publication", "medical_content"],
            signing_secret=SECRET,
        )
        record["approved_by"] = "attacker"
        with self.assertRaisesRegex(PermissionError, "signature"):
            verify_approval(bundle, record, SECRET)

    def test_preview_contains_all_approval_material(self):
        preview = render_preview(sample_bundle())
        self.assertIn("Exact approved text", preview)
        self.assertIn("Accurate visual description", preview)
        self.assertIn("LinkedIn", preview)
        self.assertIn("https://example.com/source", preview)
        self.assertIn("Build accurate visibility", preview)
        self.assertIn("medical_content", preview)

    def test_published_target_is_returned_without_second_call(self):
        bundle = sample_bundle()
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExecutionLedger(Path(directory) / "ledger.json")
            calls = []

            def publish(payload, key):
                calls.append((payload, key))
                return {
                    "url": "https://example.com/post/1",
                    "provider_receipt": "provider-123",
                }

            first = ledger.execute(bundle, bundle["targets"][0], publish)
            second = ledger.execute(bundle, bundle["targets"][0], publish)
            self.assertEqual(len(calls), 1)
            self.assertEqual(first, second)
            self.assertEqual(first["status"], "published")
            self.assertIn("idempotency_key", first)
            self.assertIn("request_sha256", first)
            self.assertEqual(first["provider_receipt"], "provider-123")

    def test_ambiguous_remote_failure_never_auto_retries(self):
        bundle = sample_bundle()
        with tempfile.TemporaryDirectory() as directory:
            ledger = ExecutionLedger(Path(directory) / "ledger.json")

            def fail(_payload, _key):
                raise TimeoutError("remote response lost")

            with self.assertRaises(TimeoutError):
                ledger.execute(bundle, bundle["targets"][0], fail)
            with self.assertRaises(ReconciliationRequired):
                ledger.execute(
                    bundle,
                    bundle["targets"][0],
                    lambda _payload, _key: {"url": "must-not-run"},
                )


if __name__ == "__main__":
    unittest.main()
