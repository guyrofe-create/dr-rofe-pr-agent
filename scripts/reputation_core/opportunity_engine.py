"""P4 evidence-led opportunity scoring and preparation selection."""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse


ACTION_TYPES = {
    "strengthen_existing_asset": {
        "impact": 8, "time": 4, "cost": 2, "risk": 2,
        "approval": "owner",
    },
    "correct_profile_or_fact": {
        "impact": 9, "time": 3, "cost": 2, "risk": 3,
        "approval": "owner",
    },
    "create_new_content": {
        "impact": 8, "time": 6, "cost": 4, "risk": 3,
        "approval": "medical_editor",
    },
    "refresh_existing_content": {
        "impact": 8, "time": 3, "cost": 2, "risk": 2,
        "approval": "medical_editor",
    },
    "connect_assets": {
        "impact": 7, "time": 2, "cost": 1, "risk": 2,
        "approval": "owner",
    },
    "create_media_or_page": {
        "impact": 7, "time": 6, "cost": 5, "risk": 3,
        "approval": "medical_editor",
    },
    "propose_new_asset": {
        "impact": 8, "time": 9, "cost": 8, "risk": 6,
        "approval": "owner",
    },
    "request_correction_or_removal": {
        "impact": 10, "time": 5, "cost": 4, "risk": 6,
        "approval": "owner_legal",
    },
    "earn_external_mention": {
        "impact": 9, "time": 7, "cost": 5, "risk": 4,
        "approval": "owner",
    },
}

LEGACY_ACTION_MAP = {
    "asset_audit": "correct_profile_or_fact",
    "ai_visibility_correction": "correct_profile_or_fact",
    "activate_asset": "strengthen_existing_asset",
    "defend_asset": "strengthen_existing_asset",
    "strengthen_asset": "strengthen_existing_asset",
    "portfolio_remediation": "strengthen_existing_asset",
    "publish_original": "create_new_content",
    "refresh_content": "refresh_existing_content",
    "connect_assets": "connect_assets",
    "create_media_or_page": "create_media_or_page",
    "create_or_earn_new_asset": "propose_new_asset",
    "displacement_campaign": "request_correction_or_removal",
    "policy_removal": "request_correction_or_removal",
    "digital_pr": "earn_external_mention",
}

PUBLIC_ACTION_TYPES = set(ACTION_TYPES)

DEFAULT_POLICY = {
    "minimum_score": 20,
    "maximum_selected_per_cycle": 5,
    "maximum_per_asset": 2,
    "maximum_risk": 6,
    "maximum_high_risk_per_cycle": 1,
    "high_risk_starts_at": 5,
}


def _clamp(value, minimum=1.0, maximum=10.0) -> float:
    return round(max(minimum, min(maximum, float(value))), 2)


def _host(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def _asset_key(asset: dict | None) -> str | None:
    if not asset:
        return None
    return (
        asset.get("id")
        or asset.get("platform")
        or _host(asset.get("url"))
        or None
    )


def _id(payload: str) -> str:
    return "opp_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def score_opportunity(
    expected_impact: float,
    asset_authority: float,
    query_relevance: float,
    control: float,
    time_cost: float,
    financial_cost: float,
    risk: float,
) -> dict:
    """Apply the P4 benefit-product / burden formula on a 1-10 scale."""
    impact = _clamp(expected_impact)
    authority = _clamp(asset_authority)
    relevance = _clamp(query_relevance)
    control_value = _clamp(control)
    time_value = _clamp(time_cost)
    cost_value = _clamp(financial_cost)
    risk_value = _clamp(risk)
    benefit_product = impact * authority * relevance * control_value
    burden_sum = time_value + cost_value + risk_value
    raw_priority_index = benefit_product / burden_sum
    normalized_burden = 0.25 + burden_sum / 30
    score = min(
        100.0,
        100
        * (impact / 10)
        * (authority / 10)
        * (relevance / 10)
        * (control_value / 10)
        / normalized_burden,
    )
    return {
        "expected_impact": impact,
        "asset_authority": authority,
        "query_relevance": relevance,
        "control": control_value,
        "time_cost": time_value,
        "financial_cost": cost_value,
        "risk": risk_value,
        "benefit_product": round(benefit_product, 4),
        "burden_sum": round(burden_sum, 4),
        "raw_priority_index": round(raw_priority_index, 4),
        "opportunity_score": round(score, 2),
        "formula": (
            "impact × authority × relevance × control ÷ "
            "(time + financial cost + risk)"
        ),
    }


def _authority(asset: dict | None, action_type: str) -> float:
    if asset:
        if asset.get("priority") is not None:
            return _clamp(float(asset["priority"]) / 10)
        return {"A": 9, "B": 7, "C": 4}.get(asset.get("tier"), 5)
    if action_type == "earn_external_mention":
        return 8
    if action_type == "request_correction_or_removal":
        return 7
    if action_type == "propose_new_asset":
        return 3
    return 5


def _control(asset: dict | None, action_type: str) -> float:
    if asset and asset.get("controlled"):
        return 10
    return {
        "earn_external_mention": 3,
        "request_correction_or_removal": 3,
        "propose_new_asset": 5,
    }.get(action_type, 6)


def _query_relevance(query: str, query_priorities: dict[str, int]) -> float:
    priority = query_priorities.get(query)
    return _clamp(priority / 10 if priority is not None else 8)


def _confidence(evidence: dict, measured: bool) -> float:
    confidence = 0.55
    if measured:
        confidence += 0.2
    if evidence:
        confidence += 0.1
    if evidence.get("impressions", 0):
        confidence += 0.1
    return round(min(confidence, 0.95), 2)


def _approval_bundle(action_type: str) -> list[str]:
    common = [
        "Evidence and exact target",
        "Expected benefit, cost, risk and measurement plan",
        "Exact proposed change or outreach text",
        "Rollback or stop condition",
    ]
    if action_type == "request_correction_or_removal":
        return common + [
            "Preserved URL, content, date and screenshot",
            "Exact platform policy or legal basis",
        ]
    if action_type == "propose_new_asset":
        return common + [
            "Distinct audience and intent proof",
            "Twelve-month ownership and maintenance plan",
        ]
    if action_type in {
        "create_new_content", "refresh_existing_content",
        "create_media_or_page",
    }:
        return common + [
            "Complete draft and sources",
            "Medical and publication policy validation",
        ]
    return common


def build_opportunity(
    action: dict,
    assets: list[dict],
    query_priorities: dict[str, int],
) -> dict | None:
    action_type = action.get("action_type") or LEGACY_ACTION_MAP.get(
        action.get("kind")
    )
    if action_type not in ACTION_TYPES:
        return None
    asset = next(
        (
            item for item in assets
            if _asset_key(item) == action.get("asset_id")
            or (
                action.get("asset_url")
                and _host(item.get("url")) == _host(action["asset_url"])
            )
        ),
        None,
    )
    defaults = ACTION_TYPES[action_type]
    evidence = action.get("evidence") or {}
    measured = bool(
        evidence
        or action.get("source_measurement")
        or action.get("source_kind")
    )
    factors = score_opportunity(
        action.get("impact", defaults["impact"]),
        action.get("authority", _authority(asset, action_type)),
        action.get(
            "relevance",
            _query_relevance(action.get("query") or "", query_priorities),
        ),
        action.get("control", _control(asset, action_type)),
        action.get("time_cost", defaults["time"]),
        action.get("financial_cost", defaults["cost"]),
        action.get("risk", defaults["risk"]),
    )
    asset_id = _asset_key(asset) or action.get("asset_id")
    identity = "|".join([
        action_type,
        str(asset_id or action.get("asset_url") or ""),
        str(action.get("query") or ""),
        str(action.get("reason") or ""),
    ])
    blocked_reasons = []
    if asset and (
        asset.get("status") == "quarantined"
        or asset.get("automation") in {
            "owner_managed_product_disabled",
            "disabled_pending_platform_resolution",
        }
    ):
        blocked_reasons.append("asset is not product-managed")
    if (
        action_type == "propose_new_asset"
        and (action.get("asset_gate") or {}).get("outcome") == "reject"
    ):
        blocked_reasons.append("new-asset safety gate rejected the proposal")
    approval = action.get("approval_required") or defaults["approval"]
    return {
        "id": _id(identity),
        "version": 4,
        "action_type": action_type,
        "kind": action.get("kind") or action_type,
        "source_kind": action.get("source_kind") or action.get("kind"),
        "asset_id": asset_id,
        "asset_url": action.get("asset_url") or (asset or {}).get("url"),
        "query": action.get("query"),
        "reason": action.get("reason"),
        "recommended_actions": (
            action.get("actions")
            or action.get("recommended_actions")
            or []
        ),
        "evidence": evidence,
        "factors": factors,
        "score": factors["opportunity_score"],
        "confidence": _confidence(evidence, measured),
        "status": "blocked" if blocked_reasons else "ranked",
        "blocked_reasons": blocked_reasons,
        "preparation_autonomous": True,
        "final_execution_requires_approval": action_type in PUBLIC_ACTION_TYPES,
        "approval_required": approval,
        "approval_bundle_requirements": _approval_bundle(action_type),
        "measurement_after_action": [
            "Re-measure the same engine, surface, query and locale",
            "Compare against 7-day and 28-day baselines",
            "Stop or reverse if risk, duplication or cannibalization rises",
        ],
    }


def _synthetic_actions(
    assets: list[dict],
    visibility_measurement: dict,
    objective: dict,
) -> list[dict]:
    actions = []
    controlled = [
        asset for asset in assets
        if asset.get("controlled")
        and asset.get("tier") in {"A", "B"}
        and asset.get("status") != "quarantined"
    ]
    strongest = max(
        controlled, key=lambda item: item.get("priority", 0), default=None
    )
    for measurement in visibility_measurement.get("serp_surfaces", []):
        query = measurement.get("query")
        gap = max(
            0,
            int(objective.get("desired_results_target", 7))
            - int(measurement.get("desired_count_top10", 0)),
        )
        source = {
            "engine": measurement.get("engine"),
            "surface": measurement.get("surface"),
            "device": measurement.get("device"),
            "desired_gap": gap,
        }
        if gap and strongest:
            actions.extend([
                {
                    "kind": "create_new_content",
                    "action_type": "create_new_content",
                    "asset_id": _asset_key(strongest),
                    "asset_url": strongest.get("url"),
                    "query": query,
                    "reason": f"Measured desired-result gap is {gap}.",
                    "actions": [
                        "Prepare one original query-relevant content brief",
                        "Choose the strongest distinct existing property",
                        "Submit the complete sourced draft for item approval",
                    ],
                    "evidence": source,
                },
                {
                    "kind": "connect_assets",
                    "action_type": "connect_assets",
                    "asset_id": _asset_key(strongest),
                    "asset_url": strongest.get("url"),
                    "query": query,
                    "reason": f"Measured desired-result gap is {gap}.",
                    "actions": [
                        "Map relevant approved assets and their distinct intents",
                        "Prepare natural contextual links without reciprocal spam",
                    ],
                    "evidence": source,
                },
                {
                    "kind": "digital_pr",
                    "action_type": "earn_external_mention",
                    "query": query,
                    "reason": f"Measured desired-result gap is {gap}.",
                    "actions": [
                        "Identify one genuinely relevant publisher or journalist",
                        "Prepare a useful evidence-led angle, not a biography pitch",
                    ],
                    "evidence": source,
                },
            ])
        features = measurement.get("features") or {}
        missing_media = [
            feature for feature in ("images", "video")
            if features.get(feature) is False
        ]
        if missing_media and strongest:
            actions.append({
                "kind": "create_media_or_page",
                "action_type": "create_media_or_page",
                "asset_id": _asset_key(strongest),
                "asset_url": strongest.get("url"),
                "query": query,
                "reason": (
                    "The observed SERP lacks these approved media surfaces: "
                    + ", ".join(missing_media)
                ),
                "actions": [
                    "Prepare the highest-value missing visual, video, document or page",
                    "Include accessible text, natural alt text, sources and canonical URL",
                ],
                "evidence": {**source, "missing_media": missing_media},
            })
        if measurement.get("negative_count_top10", 0):
            actions.append({
                "kind": "policy_removal",
                "action_type": "request_correction_or_removal",
                "query": query,
                "reason": (
                    f"{measurement['negative_count_top10']} negative result(s) "
                    "occupy the measured top ten."
                ),
                "actions": [
                    "Preserve the evidence",
                    "Assess factual correction, platform policy and lawful removal",
                    "Prepare one precise request only when a valid basis exists",
                ],
                "evidence": {
                    **source,
                    "negative_positions": measurement.get(
                        "negative_positions", []
                    ),
                },
            })
    for measurement in visibility_measurement.get("ai_surfaces", []):
        if measurement.get("factual_accuracy_rate", 1) < objective.get(
            "ai_factual_accuracy_target", 1
        ):
            actions.append({
                "kind": "ai_visibility_correction",
                "action_type": "correct_profile_or_fact",
                "query": measurement.get("prompt"),
                "reason": "Measured AI factual accuracy is below target.",
                "actions": [
                    "Trace the error to the cited or missing source",
                    "Prepare a source-first factual correction",
                    "Re-test the exact same surface and prompt after approval",
                ],
                "evidence": {
                    "engine": measurement.get("engine"),
                    "surface": measurement.get("surface"),
                    "interface": measurement.get("interface"),
                    "factual_accuracy_rate": measurement.get(
                        "factual_accuracy_rate"
                    ),
                },
            })
    return actions


def select_opportunities(
    opportunities: list[dict],
    policy: dict | None = None,
    *,
    content_freeze: bool = False,
) -> dict:
    rules = {**DEFAULT_POLICY, **(policy or {})}
    ranked = sorted(
        opportunities,
        key=lambda item: (
            item.get("status") == "blocked",
            -item.get("score", 0),
            -item.get("confidence", 0),
            item.get("factors", {}).get("risk", 10),
        ),
    )
    selected = []
    per_asset = Counter()
    high_risk = 0
    for item in ranked:
        if item["status"] == "blocked":
            continue
        risk = item["factors"]["risk"]
        if item["score"] < rules["minimum_score"]:
            item["status"] = "deferred_below_score"
            continue
        if risk > rules["maximum_risk"]:
            item["status"] = "deferred_risk_ceiling"
            continue
        if len(selected) >= rules["maximum_selected_per_cycle"]:
            item["status"] = "deferred_capacity"
            continue
        if item.get("asset_id") and per_asset[item["asset_id"]] >= rules[
            "maximum_per_asset"
        ]:
            item["status"] = "deferred_asset_concentration"
            continue
        if risk >= rules["high_risk_starts_at"]:
            if high_risk >= rules["maximum_high_risk_per_cycle"]:
                item["status"] = "deferred_high_risk_capacity"
                continue
            high_risk += 1
        item["status"] = "selected_for_preparation"
        item["execution_mode"] = (
            "prepare_only_due_to_content_freeze"
            if content_freeze
            else "autonomous_prepare_then_approval"
        )
        selected.append(item)
        if item.get("asset_id"):
            per_asset[item["asset_id"]] += 1
    return {
        "policy": rules,
        "ranked_opportunities": ranked,
        "selected_for_preparation": selected,
        "deferred": [
            item for item in ranked
            if item["status"].startswith("deferred")
            or item["status"] == "blocked"
        ],
    }


def build_opportunity_portfolio(
    legacy_actions: list[dict],
    new_asset_proposals: list[dict],
    assets: list[dict],
    visibility_measurement: dict,
    objective: dict,
    query_priorities: dict[str, int],
    *,
    policy: dict | None = None,
    content_freeze: bool = False,
    now: datetime | None = None,
) -> dict:
    source_actions = list(legacy_actions)
    source_actions.extend(new_asset_proposals)
    source_actions.extend(
        _synthetic_actions(assets, visibility_measurement, objective)
    )
    built = [
        opportunity
        for action in source_actions
        if (
            opportunity := build_opportunity(
                action, assets, query_priorities
            )
        )
    ]
    unique = {}
    for item in built:
        existing = unique.get(item["id"])
        if existing is None or item["score"] > existing["score"]:
            unique[item["id"]] = item
    selection = select_opportunities(
        list(unique.values()), policy, content_freeze=content_freeze
    )
    generated = now or datetime.now(timezone.utc)
    ranked = selection["ranked_opportunities"]
    return {
        "version": 4,
        "generated_at": generated.replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
        "objective": (
            "Choose the highest expected reputation return per unit of time, "
            "cost and risk; prepare autonomously and require approval before "
            "public execution."
        ),
        "formula": (
            "expected impact × asset authority × query relevance × control "
            "÷ (time + financial cost + risk)"
        ),
        **selection,
        "action_type_counts": dict(Counter(
            item["action_type"] for item in ranked
        )),
        "selected_score_total": round(sum(
            item["score"]
            for item in selection["selected_for_preparation"]
        ), 2),
        "calendar_rule": (
            "Opportunity score and capacity decide preparation; fixed weekdays "
            "do not decide priority."
        ),
    }
