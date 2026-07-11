"""Campaign planner for durable Google and AI-search reputation control."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from .tactics import TACTICS, ranked_tactics


ASSET_TYPES = [
    "canonical_site", "professional_profile", "publisher_profile", "knowledge_entity",
    "video_channel", "social_profile", "podcast_profile", "independent_media",
    "review_profile", "association_profile",
]


def _id(prefix, value):
    return prefix + hashlib.sha256(value.encode("utf-8")).hexdigest()[:14]


def build_serp_asset_gap(current_assets: list[dict], target_slots: int = 8) -> dict:
    healthy = [a for a in current_assets if a.get("status", "active") == "active"]
    page_one = [a for a in healthy if a.get("page_one") is True]
    types = {a.get("type") for a in healthy}
    missing = [kind for kind in ASSET_TYPES if kind not in types]
    controlled = sum(bool(a.get("controlled")) for a in page_one)
    independent = sum(not bool(a.get("controlled")) for a in page_one)
    return {
        "target_slots": target_slots,
        "eligible_assets": len(healthy),
        "observed_page_one_assets": len(page_one),
        "controlled_page_one_assets": controlled,
        "independent_page_one_assets": independent,
        "slot_gap": max(0, target_slots - len(page_one)),
        "missing_asset_types": missing,
        "warning": "Asset existence is not page-one visibility. Slots count only observed page-one results; independent editorial results must be earned.",
    }


def plan_growth_campaign(profile: dict, observations: dict) -> dict:
    """Create a high-cadence campaign from observable gaps, never promises."""
    brand = profile.get("name", "brand")
    assets = observations.get("serp_assets", [])
    asset_gap = build_serp_asset_gap(assets)
    tasks = []

    def add(tactic_id, reason, priority):
        tactic = TACTICS[tactic_id]
        tasks.append({
            "id": _id("gt_", f"{brand}|{tactic_id}|{reason}"),
            "tactic": tactic_id,
            "priority": priority,
            "reason": reason,
            "surface": tactic["surface"],
            "status": "proposed",
            "approval_required": "manager" if tactic["risk"] >= 2 else "standard",
            "actions": tactic["actions"],
            "forbidden": tactic["forbidden"],
            "impact": tactic["impact"],
            "speed": tactic["speed"],
            "risk": tactic["risk"],
        })

    if not observations.get("canonical_entity_complete"):
        add("entity_home", "canonical entity and corroborated facts are incomplete", "P1")
    if asset_gap["slot_gap"]:
        add("brand_serp_asset", f"brand SERP has an estimated {asset_gap['slot_gap']}-asset gap", "P1")
    if observations.get("local_rank_weak"):
        add("local_prominence", "local commercial queries underperform", "P1")
    if observations.get("pages_position_4_20", 0):
        add("content_refresh", f"{observations['pages_position_4_20']} pages are within striking distance", "P1")
    if observations.get("ai_citation_gap") or observations.get("ai_mention_gap"):
        add("expert_answer_library", "AI citation or explicit brand-mention coverage is weak", "P1")
        add("original_research", "independent citable evidence is needed", "P2")
    if observations.get("independent_authority_gap"):
        add("digital_pr", "third-party authority and corroboration are insufficient", "P1")
    if observations.get("eligible_policy_violations", 0):
        add("policy_removal", f"{observations['eligible_policy_violations']} items may qualify for policy review", "P1")

    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4}
    tasks.sort(key=lambda t: (order[t["priority"]], -(t["impact"] * 2 + t["speed"] - t["risk"] * 2)))
    return {
        "id": _id("cmp_", f"{brand}|{datetime.now(timezone.utc).date().isoformat()}"),
        "brand": brand,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "objective": "Maximize accurate first-page brand coverage and recommendation visibility across search and AI surfaces",
        "guardrail": "No ranking or citation can be guaranteed; optimize controllable eligibility, authority, evidence and demand signals.",
        "serp_asset_gap": asset_gap,
        "tasks": tasks,
        "available_tactics": [t["id"] for t in ranked_tactics(max_risk=3)],
        "success_metrics": [
            "first_page_asset_coverage", "positive_or_neutral_first_page_share", "brand_search_demand",
            "local_pack_share_of_voice", "organic_nonbrand_share_of_voice", "ai_citation_share",
            "ai_explicit_mention_share", "ai_sentiment", "qualified_leads", "reputation_incidents_resolved",
        ],
    }
