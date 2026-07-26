"""Automatic stop rules for maximum-sustainable reputation coverage."""
from __future__ import annotations

from .asset_safety import allowed_new_asset_volume


STOP_RISKS = {
    "cross_domain_duplicate",
    "query_cannibalization",
    "doorway_pattern",
    "thin_content",
    "indexing_anomaly",
    "manual_action",
}


def evaluate_coverage_safety(
    assets: list[dict],
    cross_domain_risks: list[dict],
    policy: dict,
) -> dict:
    """Return expand/hold/stop based on value, health and observed risk."""
    active = [
        asset for asset in assets
        if asset.get("controlled")
        and asset.get("tier") in {"A", "B"}
        and asset.get("status") not in {"quarantined", "retired", "disabled"}
    ]
    known_health = [
        float(asset["maintenance_health"])
        for asset in active
        if asset.get("maintenance_health") is not None
    ]
    health = sum(known_health) / len(known_health) if known_health else 0.0
    signals = {
        risk.get("type") for risk in cross_domain_risks
    } | {
        signal
        for asset in active
        for signal in asset.get("risk_signals", [])
    }
    hard = sorted(signals & STOP_RISKS)
    capacity = allowed_new_asset_volume(policy, health, active)
    reasons = []
    if hard:
        mode = "stop"
        reasons.append("automatic stop: " + ", ".join(hard))
    elif health < float(policy["minimum_maintenance_health"]):
        mode = "hold"
        reasons.append("portfolio maintenance health is below the configured floor")
    elif capacity <= 0:
        mode = "hold"
        reasons.append("no measured maintenance capacity remains")
    else:
        mode = "expand"
        reasons.append("portfolio is differentiated, healthy and has measured capacity")
    return {
        "mode": mode,
        "portfolio_health": round(health, 4),
        "active_assets": len(active),
        "available_asset_capacity": capacity,
        "signals": sorted(signals),
        "reasons": reasons,
        "rule": (
            "Never infer Google's penalty threshold. Expand only from independent "
            "value, differentiation, authority, maintenance and index health."
        ),
    }
