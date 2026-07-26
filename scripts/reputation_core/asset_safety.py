"""Quality and volume guardrails for controlled reputation assets.

There is no universal safe number of sites or profiles. The gate therefore
uses portfolio health, distinct user purpose, content runway, maintenance
capacity and observed search health. It fails closed on doorway, cloning and
other spam-like patterns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class AssetGateDecision:
    outcome: str
    score: int
    volume_limit: int
    reasons: list[str]
    required_actions: list[str]


def _as_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def allowed_new_asset_volume(
    policy: dict,
    portfolio_health: float,
    active_assets: list[dict] | None = None,
) -> int:
    """Return capacity-derived volume, never a universal platform threshold."""
    if portfolio_health < float(policy["minimum_maintenance_health"]):
        return 0
    capacity = float(policy.get("maintenance_capacity_units", 0))
    default_cost = float(policy.get("default_asset_maintenance_units", 1))
    load = sum(
        float(asset.get("maintenance_units", default_cost))
        for asset in (active_assets or [])
    )
    spare = max(0.0, capacity - load)
    candidate_cost = max(0.1, float(policy.get("new_asset_maintenance_units", default_cost)))
    return int(spare // candidate_cost)


def evaluate_asset_candidate(
    candidate: dict,
    existing_assets: list[dict],
    creation_history: list[dict],
    policy: dict,
    now: datetime | None = None,
) -> AssetGateDecision:
    """Decide whether to build, incubate or reject a proposed asset."""
    now = now or datetime.now(timezone.utc)
    signals = set(candidate.get("risk_signals", []))
    hard_stops = signals & set(policy.get("hard_stop_signals", []))
    if hard_stops:
        return AssetGateDecision(
            "reject",
            0,
            0,
            ["hard-stop signal: " + ", ".join(sorted(hard_stops))],
            ["Strengthen or clean an existing asset before proposing another."],
        )

    active = [
        asset for asset in existing_assets
        if asset.get("controlled")
        and asset.get("status") not in {"quarantined", "retired", "disabled"}
    ]
    health_values = [
        float(asset.get("maintenance_health", 0.0))
        for asset in active
        if asset.get("maintenance_health") is not None
    ]
    portfolio_health = (
        sum(health_values) / len(health_values) if health_values else 0.0
    )
    volume_limit = allowed_new_asset_volume(policy, portfolio_health, active)
    cutoff = now - timedelta(days=90)
    recent_creations = [
        item for item in creation_history
        if (_as_time(item.get("created_at")) or datetime.min.replace(
            tzinfo=timezone.utc
        )) >= cutoff
        and item.get("kind") == "standalone"
    ]

    reasons = []
    required_actions = []
    score = 0
    distinct_purpose = int(candidate.get("distinct_purpose_score", 0))
    content_runway = int(candidate.get("content_runway_items", 0))
    maintenance_owner = bool(candidate.get("maintenance_owner"))
    authority_path = bool(candidate.get("authority_path"))
    measurable = bool(candidate.get("measurement_plan"))
    audience = bool(candidate.get("distinct_audience"))

    score += min(25, distinct_purpose // 4)
    score += 20 if audience else 0
    score += 20 if maintenance_owner else 0
    score += 15 if authority_path else 0
    score += 10 if measurable else 0
    score += min(10, content_runway)

    if distinct_purpose < int(policy["minimum_distinct_purpose_score"]):
        reasons.append("purpose is not sufficiently distinct")
        required_actions.append("Test the concept as a section or series first.")
    if content_runway < int(policy["minimum_content_runway_items"]):
        reasons.append("insufficient original content runway")
        required_actions.append(
            f"Document at least {policy['minimum_content_runway_items']} "
            "non-duplicative content items."
        )
    if not maintenance_owner:
        reasons.append("no accountable maintenance owner")
    if portfolio_health < float(policy["minimum_maintenance_health"]):
        reasons.append("existing controlled portfolio is not healthy enough")
        required_actions.append("Repair stale or incomplete controlled assets first.")
    if volume_limit <= 0:
        reasons.append("measured maintenance capacity has no room for another asset")
    if len(recent_creations) >= volume_limit:
        reasons.append("90-day standalone-asset volume budget is exhausted")

    capacity_blocked = (
        volume_limit <= 0
        or len(recent_creations) >= volume_limit
        or portfolio_health < float(policy["minimum_maintenance_health"])
    )
    quality_blocked = (
        distinct_purpose < int(policy["minimum_distinct_purpose_score"])
        or content_runway < int(policy["minimum_content_runway_items"])
        or not maintenance_owner
    )

    if score >= int(policy["minimum_build_score"]) and not (
        capacity_blocked or quality_blocked
    ):
        outcome = "build"
        reasons.append("candidate has distinct value and sustainable capacity")
    elif policy.get("incubate_new_concepts_inside_existing_asset_first", True):
        outcome = "incubate"
        reasons.append("prove demand and differentiation inside an existing asset")
    else:
        outcome = "reject"

    return AssetGateDecision(
        outcome,
        score,
        volume_limit,
        reasons,
        required_actions,
    )
