"""Prioritize the complete public asset portfolio without copying credentials."""
from __future__ import annotations

from datetime import datetime, timezone


BLOCKED_STATUSES = {
    "quarantined", "suspended_or_inaccessible", "missing_profile_url",
    "paused_missing_credentials", "owner_managed_product_disabled",
}


def _asset_actions(asset: dict, reachability: dict | None, effort: str) -> list[str]:
    reachability = reachability or {}
    platform = str(asset.get("platform") or "")
    url = str(asset.get("url") or "").rstrip("/")
    if platform == "Google Business Profile":
        return [
            "preserve_core_profile_configuration",
            "continue_exact_approved_information_posts_media_and_contextual_links",
            "measure_search_and_maps_visibility",
        ]
    if platform == "Canonical website" and url == "https://guyrofe.com":
        return ["monitor_rank_and_indexation_without_content_or_structure_changes"]
    actions: list[str] = []
    public_state = reachability.get("reachability", "not_checked")
    if public_state in {"not_found", "network_or_provider_error", "http_error"}:
        actions.append("repair_or_confirm_public_url")
    if public_state in {"access_restricted_or_anti_bot", "not_checked"}:
        actions.append("manual_browser_audit")
    if reachability.get("content_audit") == "complete":
        issue_prefix = "fix" if asset.get("controlled") else "request_or_document"
        actions.extend(
            f"{issue_prefix}_{issue}" for issue in reachability.get("seo_issues", [])
        )
        if not reachability.get("entity_in_title") and effort in {"core", "defend", "selective"}:
            actions.append("review_entity_name_in_title")
        if not reachability.get("official_link_present") and effort in {"core", "defend", "selective"}:
            actions.append("add_reader_useful_official_link_if_platform_allows")
    elif public_state == "reachable":
        actions.append("manual_content_and_profile_field_audit")
    status = str(asset.get("status") or "")
    if "audit_required" in status or status in {"accuracy_audit_required", "factual_audit_required", "urgent_content_audit"}:
        actions.append("complete_registered_factual_audit")
    if asset.get("type") in {"book_product", "podcast", "podcast_profile", "video_channel"}:
        actions.append("measure_exact_brand_serp_and_search_console_visibility")
    return list(dict.fromkeys(actions))


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

    actions = _asset_actions(asset, reachability, effort)
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
        "content_audit": (reachability or {}).get("content_audit", "not_checked"),
        "title": (reachability or {}).get("title"),
        "meta_description": (reachability or {}).get("meta_description"),
        "canonical": (reachability or {}).get("canonical"),
        "noindex": (reachability or {}).get("noindex"),
        "entity_in_title": (reachability or {}).get("entity_in_title"),
        "entity_in_page": (reachability or {}).get("entity_in_page"),
        "official_link_present": (reachability or {}).get("official_link_present"),
        "schema_types": (reachability or {}).get("schema_types", []),
        "seo_issues": (reachability or {}).get("seo_issues", []),
        "action_checklist": actions,
        "audit_complete": not actions,
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
        "version": 2,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "objective": "Maximize accurate first-page and discovery visibility with the existing asset portfolio.",
        "policy": "Effort follows authority, measured visibility, audience fit and control; account count alone is not a success metric.",
        "asset_count": len(rows),
        "effort_counts": counts,
        "audit_complete_count": sum(1 for row in rows if row["audit_complete"]),
        "action_required_count": sum(1 for row in rows if not row["audit_complete"]),
        "assets": rows,
        "credentials_included": False,
        "public_execution_allowed": False,
    }
