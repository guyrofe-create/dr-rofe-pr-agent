"""P7 immutable approval bundles, explicit approvals and publication receipts."""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SENSITIVE_APPROVAL_SCOPES = frozenset(
    {
        "public_publication",
        "domain_purchase",
        "account_creation",
        "medical_content",
        "legal_claim",
        "external_outreach",
    }
)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _material(bundle: dict) -> dict:
    return {
        "version": bundle["version"],
        "action_type": bundle["action_type"],
        "source_draft": bundle.get("source_draft"),
        "source_draft_sha256": bundle.get("source_draft_sha256"),
        "objective": bundle["objective"],
        "query": bundle["query"],
        "sources": bundle.get("sources", []),
        "media": bundle.get("media"),
        "targets": bundle["targets"],
        "risk": bundle["risk"],
        "compliance": bundle["compliance"],
        "required_approval_scopes": sorted(bundle["required_approval_scopes"]),
    }


def approval_id(bundle: dict) -> str:
    return f"apr_{sha256(_material(bundle))}"


def build_bundle(
    *,
    action_type: str,
    objective: str,
    query: str,
    targets: list[dict],
    sources: list[dict] | list[str],
    risk: dict,
    compliance: dict,
    media: dict | None = None,
    sensitive_actions: list[str] | None = None,
    source_draft: str | None = None,
    source_draft_sha256: str | None = None,
    created_at: str | None = None,
) -> dict:
    """Build one exact, immutable package for a single approval decision."""
    if not targets:
        raise ValueError("An approval bundle must contain at least one target")
    for target in targets:
        for field in ("target_id", "platform", "asset", "payload"):
            if field not in target:
                raise ValueError(f"Target is missing required field: {field}")
    requested = set(sensitive_actions or [])
    unknown = requested - SENSITIVE_APPROVAL_SCOPES
    if unknown:
        raise ValueError(f"Unknown sensitive approval scopes: {sorted(unknown)}")
    required = {"public_publication"} | requested
    bundle = {
        "version": 7,
        "status": "awaiting_explicit_approval",
        "created_at": created_at or utc_now(),
        "action_type": action_type,
        "source_draft": source_draft,
        "source_draft_sha256": source_draft_sha256,
        "objective": objective,
        "query": query,
        "sources": sources,
        "media": media,
        "targets": targets,
        "risk": risk,
        "compliance": compliance,
        "required_approval_scopes": sorted(required),
        "any_material_edit_invalidates_approval": True,
        "public_execution_allowed": False,
    }
    bundle["approval_id"] = approval_id(bundle)
    return bundle


def validate_bundle(bundle: dict) -> None:
    expected = approval_id(bundle)
    if not hmac.compare_digest(str(bundle.get("approval_id", "")), expected):
        raise ValueError("Approval bundle has changed or has an invalid approval_id")
    required = set(bundle.get("required_approval_scopes", []))
    if "public_publication" not in required:
        raise ValueError("Public publication approval is always required")
    unknown = required - SENSITIVE_APPROVAL_SCOPES
    if unknown:
        raise ValueError(f"Unknown approval scopes: {sorted(unknown)}")


def _approval_claim(record: dict) -> dict:
    return {
        "approval_id": record["approval_id"],
        "approved_by": record["approved_by"],
        "approved_at": record["approved_at"],
        "approved_scopes": sorted(record["approved_scopes"]),
        "decision": record["decision"],
    }


def approve_bundle(
    bundle: dict,
    *,
    approved_by: str,
    approved_scopes: list[str],
    signing_secret: str,
    approved_at: str | None = None,
) -> dict:
    """Sign an explicit approval for every scope required by the exact bundle."""
    validate_bundle(bundle)
    if not approved_by.strip():
        raise ValueError("approved_by is required")
    if len(signing_secret) < 24:
        raise ValueError("Approval signing secret must contain at least 24 characters")
    required = set(bundle["required_approval_scopes"])
    supplied = set(approved_scopes)
    missing = required - supplied
    if missing:
        raise PermissionError(
            f"Explicit approval is missing required scopes: {sorted(missing)}"
        )
    record = {
        "version": 7,
        "approval_id": bundle["approval_id"],
        "decision": "approved",
        "approved_by": approved_by.strip(),
        "approved_at": approved_at or utc_now(),
        "approved_scopes": sorted(supplied),
    }
    record["signature"] = hmac.new(
        signing_secret.encode("utf-8"),
        canonical_json(_approval_claim(record)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return record


def verify_approval(bundle: dict, record: dict, signing_secret: str) -> None:
    validate_bundle(bundle)
    if record.get("decision") != "approved":
        raise PermissionError("The approval record is not approved")
    if not hmac.compare_digest(
        str(record.get("approval_id", "")), bundle["approval_id"]
    ):
        raise PermissionError("Approval does not match this exact bundle")
    required = set(bundle["required_approval_scopes"])
    missing = required - set(record.get("approved_scopes", []))
    if missing:
        raise PermissionError(
            f"Explicit approval is missing required scopes: {sorted(missing)}"
        )
    expected = hmac.new(
        signing_secret.encode("utf-8"),
        canonical_json(_approval_claim(record)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(str(record.get("signature", "")), expected):
        raise PermissionError("Approval signature is invalid")


def render_preview(bundle: dict) -> str:
    """Render a review-only preview from the signed material, never vice versa."""
    validate_bundle(bundle)
    e = html.escape
    targets = []
    for target in bundle["targets"]:
        payload = e(
            json.dumps(target["payload"], ensure_ascii=False, indent=2, sort_keys=True)
        )
        targets.append(
            "<section>"
            f"<h2>{e(target['platform'])} — {e(target['asset'])}</h2>"
            f"<p><strong>Target:</strong> {e(target['target_id'])}</p>"
            f"<pre dir=\"auto\">{payload}</pre>"
            "</section>"
        )
    source_items = "".join(
        f"<li>{e(source if isinstance(source, str) else canonical_json(source))}</li>"
        for source in bundle.get("sources", [])
    )
    media = bundle.get("media") or {}
    media_html = (
        f"<p><strong>Image:</strong> {e(str(media.get('uri', 'none')))}</p>"
        f"<p><strong>Alt text:</strong> {e(str(media.get('alt_text', 'none')))}</p>"
    )
    return """<!doctype html>
<html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>חבילת אישור P7</title>
<style>body{font:16px system-ui;max-width:960px;margin:32px auto;padding:0 20px}
section{border:1px solid #ccd5df;border-radius:12px;padding:18px;margin:18px 0}
pre{white-space:pre-wrap;background:#f5f7f9;padding:14px;border-radius:8px}
.warning{background:#fff4df;border:1px solid #e8aa3e;padding:14px;border-radius:8px}</style>
</head><body>""" + (
        f"<h1>חבילת אישור אחת — {e(bundle['approval_id'])}</h1>"
        f"<p><strong>מטרה:</strong> {e(bundle['objective'])}</p>"
        f"<p><strong>שאילתה:</strong> {e(bundle['query'])}</p>"
        f"<div class=\"warning\"><strong>אישורים מפורשים:</strong> "
        f"{e(', '.join(bundle['required_approval_scopes']))}</div>"
        f"<h2>תמונה</h2>{media_html}"
        f"<h2>מקורות</h2><ul>{source_items or '<li>ללא מקורות</li>'}</ul>"
        f"<h2>סיכון וציות</h2><pre>{e(canonical_json(bundle['risk']))}</pre>"
        f"<pre>{e(canonical_json(bundle['compliance']))}</pre>"
        + "".join(targets)
        + "</body></html>"
    )


class ReconciliationRequired(RuntimeError):
    """An earlier external call may have succeeded; do not retry automatically."""


class ExecutionLedger:
    """Atomic, fail-closed idempotency ledger for externally visible actions."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 7, "executions": {}}

    def _save(self, state: dict) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @staticmethod
    def key(approval_id_value: str, target_id: str) -> str:
        return f"pub_{sha256({'approval_id': approval_id_value, 'target_id': target_id})}"

    def execute(
        self,
        bundle: dict,
        target: dict,
        publisher: Callable[[dict, str], dict],
    ) -> dict:
        key = self.key(bundle["approval_id"], target["target_id"])
        state = self._load()
        existing = state["executions"].get(key)
        if existing and existing.get("status") == "published":
            return existing
        if existing and existing.get("status") in {
            "in_progress",
            "reconciliation_required",
        }:
            existing["status"] = "reconciliation_required"
            existing["updated_at"] = utc_now()
            self._save(state)
            raise ReconciliationRequired(
                f"Target {target['target_id']} may already be published; reconcile first"
            )
        request_hash = sha256(target["payload"])
        entry = {
            "version": 7,
            "idempotency_key": key,
            "approval_id": bundle["approval_id"],
            "target_id": target["target_id"],
            "platform": target["platform"],
            "asset": target["asset"],
            "request_sha256": request_hash,
            "status": "in_progress",
            "started_at": utc_now(),
        }
        state["executions"][key] = entry
        self._save(state)
        try:
            result = publisher(target["payload"], key)
        except Exception:
            # The remote side may have accepted the request before disconnecting.
            entry["status"] = "reconciliation_required"
            entry["updated_at"] = utc_now()
            self._save(state)
            raise
        if not isinstance(result, dict) or not result.get("url"):
            entry["status"] = "reconciliation_required"
            entry["updated_at"] = utc_now()
            self._save(state)
            raise ReconciliationRequired("Publisher returned no verifiable public URL")
        entry.update(
            {
                "status": "published",
                "published_at": utc_now(),
                "url": result["url"],
                "provider_receipt": result.get("provider_receipt"),
            }
        )
        self._save(state)
        return entry
