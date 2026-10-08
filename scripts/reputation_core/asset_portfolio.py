"""Prioritize the complete public asset portfolio without copying credentials."""
from __future__ import annotations

from datetime import datetime, timezone


BLOCKED_STATUSES = {
    "quarantined", "suspended_or_inaccessible", "missing_profile_url",
    "paused_missing_credentials", "owner_managed_product_disabled",
}


def asset_effort_decision(asset: dict, reachability: dict | None = None) -> dict:
    tier = str(asset.get("tier") or "C")
    priority = int(asset.get("priority") or 0)
    status = str(asset.get("status") or "unknown")
    page_one = bool(asset.get("page_one"))
    controlled = bool(asset.get("controlled"))

    public_state = (reachability or {}).get("reachability", "not_checked")
    if tier == "Q" or status == "quarantined":
        effort = "quarantine"
        reason = "Low-quality mirror/network risk outweighs routine publishing value."
    elif public_state == "not_found":
        effort = "resolve_or_hold"
        reason = "The registered public URL returned 404/410 and must be repaired or removed before further effort."
    elif public_state == "network_or_provider_error" and tier in {"A", "B"}:
        effort = "resolve_or_hold"
        reason = "The public URL could not be resolved or reached; verify DNS and the exact destination before allocating effort."
    elif status in BLOCKED_STATUSES:
        effort = "resolve_or_hold"
        reason = "Do not spend editorial effort until the access, product or ownership blocker is resolved."
    elif tier == "A" and priority >= 85:
        effort = "core"
        reason = "High-authority owned or identity asset; maintain facts, freshness and measurement."
    elif page_one:
        effort = "defend"
        reason = "Already earns a measured first-page slot; preserve quality and factual consistency."
    elif tier == "B" and priority >= 55:
        effort = "selective"
        reason = "Use only when the platform can carry unique, audience-native material or a factual profile improvement."
    else:
        effort = "retain_only"
        reason = "Keep the account if useful, but do not allocate recurring content merely to fill inventory."

    if effort in {"core", "defend"}:
        next_action = "audit_facts_then_measure_and_maintain"
    elif effort == "selective":
        next_action = "one_time_audit_then_use_only_for_unique_fit"
    elif effort == "resolve_or_hold":
        next_action = "resolve_exact_blocker_before_any_content"
    elif effort == "quarantine":
        next_action = "no_automation_no_cross_link_network"
    else:
        next_action = "retain_without_recurring_effort"

    return {
        "platform": asset.get("platform"),
        "url": asset.get("url"),
        "tier": tier,
        "priority": priority,
        "status": status,
        "controlled": controlled,
        "page_one": page_one,
        "effort": effort,
        "reason": reason,
        "next_action": next_action,
        "reachability": public_state,
        "http_status": (reachability or {}).get("http_status"),
        "final_url": (reachability or {}).get("final_url"),
        "public_execution_allowed": False,
    }


def build_asset_portfolio_plan(
    registry: dict,
    *,
    reachability: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    reachability_rows = {
        (row.get("platform"), row.get("url")): row
        for row in (reachability or {}).get("assets", [])
    }
    rows = [
        asset_effort_decision(
            asset,
            reachability_rows.get((asset.get("platform"), asset.get("url"))),
        )
        for asset in registry.get("assets", [])
    ]
    order = {"core": 0, "defend": 1, "selective": 2, "resolve_or_hold": 3,
             "retain_only": 4, "quarantine": 5}
    rows.sort(key=lambda row: (order[row["effort"]], -row["priority"], str(row["platform"])))
    counts = {}
    for row in rows:
        counts[row["effort"]] = counts.get(row["effort"], 0) + 1
    return {
        "version": 1,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "objective": "Maximize accurate first-page and discovery visibility with the existing asset portfolio.",
        "policy": "Effort follows authority, measured visibility, audience fit and control; account count alone is not a success metric.",
        "asset_count": len(rows),
        "effort_counts": counts,
        "assets": rows,
        "credentials_included": False,
        "public_execution_allowed": False,
    }
