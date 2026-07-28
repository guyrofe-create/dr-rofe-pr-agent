"""Evidence-first controls for reputation work that can cause external harm.

These helpers prepare and validate work. They never submit a disavow file,
request a review, edit Wikipedia/Wikidata, file a legal request, claim a
Knowledge Panel, or send AI feedback.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlparse


def _host(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def audit_backlinks(
    current: list[dict],
    previous: list[dict] | None = None,
    *,
    owned_hosts: set[str] | None = None,
) -> dict:
    """Diff backlink snapshots and flag evidence for review, never auto-disavow."""
    owned = {host.lower().removeprefix("www.") for host in (owned_hosts or set())}
    before = {
        (item.get("source_url"), item.get("target_url"))
        for item in (previous or [])
    }
    links = []
    for item in current:
        source_url = item.get("source_url") or ""
        target_url = item.get("target_url") or ""
        source_host = _host(source_url)
        signals = sorted(set(item.get("risk_signals") or []))
        suspicious = bool(
            set(signals)
            & {
                "malware",
                "hacked_site",
                "paid_link_network",
                "mass_generated_anchor",
                "adult_or_gambling_mismatch",
                "negative_seo_pattern",
            }
        )
        links.append({
            **item,
            "source_host": source_host,
            "new": (source_url, target_url) not in before,
            "owned_source": source_host in owned,
            "risk_signals": signals,
            "classification": "manual_review_required" if suspicious else "observed",
        })
    candidates = [item for item in links if item["classification"] == "manual_review_required"]
    return {
        "kind": "backlink_monitor",
        "links": links,
        "new_links": sum(item["new"] for item in links),
        "manual_review_candidates": candidates,
        "disavow_submission_allowed": False,
        "disavow_policy": (
            "Do not disavow merely because a link is low quality. Require a "
            "documented pattern, manual review, exact domain list and explicit approval."
        ),
    }


def build_disavow_proposal(audit: dict, domains: list[str]) -> dict:
    reviewed = {
        item["source_host"]
        for item in audit.get("manual_review_candidates", [])
    }
    normalized = sorted({_host(domain) for domain in domains if _host(domain)})
    unsupported = sorted(set(normalized) - reviewed)
    return {
        "kind": "disavow_proposal",
        "domains": normalized,
        "status": "blocked" if unsupported or not normalized else "awaiting_explicit_approval",
        "unsupported_domains": unsupported,
        "requires_explicit_approval": True,
        "auto_submit": False,
    }


def build_review_request_campaign(
    recipients: list[dict],
    *,
    destination_url: str,
    message: str,
    incentive: str | None = None,
) -> dict:
    """Create an ungated honest-review request plan for all eligible recipients."""
    eligible = [
        item for item in recipients
        if item.get("real_interaction_verified")
        and item.get("contact_permission")
        and not item.get("opted_out")
    ]
    sentiment_fields = {
        "rating", "nps", "sentiment", "satisfaction", "likely_positive",
    }
    if any(sentiment_fields & set(item) for item in recipients):
        raise ValueError("Review-gating fields are forbidden in recipient selection")
    if incentive:
        raise ValueError("Incentivized review requests are disabled")
    if not destination_url.startswith("https://"):
        raise ValueError("A secure review destination is required")
    if not message.strip():
        raise ValueError("Review request message is required")
    return {
        "kind": "honest_review_request_campaign",
        "status": "draft_requires_approval",
        "selection_rule": "all_eligible_without_sentiment_filter",
        "recipient_ids": [item["id"] for item in eligible],
        "destination_url": destination_url,
        "message": message.strip(),
        "required_disclosure": "Honest feedback is requested whether positive or negative.",
        "incentive": None,
        "requires_external_outreach_approval": True,
        "auto_send": False,
    }


LEGAL_REQUIRED_FIELDS = {
    "case_number",
    "court",
    "document_url",
    "document_sha256",
    "retrieved_at",
    "verified_at",
    "verified_by",
    "verification_source_url",
}


def validate_legal_evidence_chain(
    record: dict,
    *,
    document_bytes: bytes | None = None,
) -> dict:
    missing = sorted(field for field in LEGAL_REQUIRED_FIELDS if not record.get(field))
    errors = []
    if document_bytes is not None and record.get("document_sha256"):
        if _sha256_bytes(document_bytes) != record["document_sha256"]:
            errors.append("document_sha256_mismatch")
    if record.get("verification_source_url") and not str(
        record["verification_source_url"]
    ).startswith("https://"):
        errors.append("verification_source_must_be_https")
    if record.get("court_record_verified") is not True:
        errors.append("court_record_not_verified")
    ready = not missing and not errors
    return {
        "kind": "legal_evidence_chain",
        "ready": ready,
        "missing_fields": missing,
        "errors": errors,
        "legal_request_allowed": False,
        "status": "awaiting_explicit_legal_approval" if ready else "blocked",
    }


def build_knowledge_panel_task(entity: dict) -> dict:
    return {
        "kind": "knowledge_panel_ownership",
        "entity": entity,
        "status": "verification_required",
        "steps": [
            "Confirm a panel exists for the exact entity and preserve a screenshot.",
            "Verify the official representative account and canonical site.",
            "Submit a claim only through Google's supported interface.",
            "Record the claim date, account, decision and evidence.",
            "Audit every displayed fact after access is granted.",
        ],
        "submission_mode": "manual_owner_action",
        "auto_claim": False,
    }


def build_ai_feedback_task(sample: dict) -> dict:
    required = {"engine", "prompt", "exact_answer", "observed_at", "error"}
    missing = sorted(field for field in required if not sample.get(field))
    return {
        "kind": "ai_answer_feedback",
        "engine": sample.get("engine"),
        "status": "blocked" if missing else "ready_for_manual_submission",
        "missing_fields": missing,
        "evidence": sample,
        "cost": 0,
        "approval_required_to_prepare": False,
        "submission_mode": "manual_user_action",
        "auto_submit": False,
    }


def build_wikimedia_workstream(entity: dict) -> dict:
    return {
        "kind": "wikipedia_wikidata_workstream",
        "entity": entity,
        "status": "independent_notability_and_source_audit_required",
        "requirements": [
            "Independent reliable secondary sources with significant coverage.",
            "Conflict-of-interest disclosure for any connected editor.",
            "No promotional language, original research or self-sourced notability.",
            "Wikidata statements must be individually sourced and accurately scoped.",
        ],
        "preferred_action": "propose_changes_on_talk_page_or_requested_edit",
        "direct_edit_authorized": False,
        "new_page_authorized": False,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
