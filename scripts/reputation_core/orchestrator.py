"""Closed-loop orchestration for maximum sustainable Google and AI visibility.

The orchestrator never promises rankings. It converts observed search results,
Search Console evidence, AI answers and the approved asset registry into a
query-level control map and a prioritized action backlog.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = PROJECT_ROOT / "config" / "serp_targets.json"

RANK_WEIGHTS = {position: 1 / position for position in range(1, 11)}
ACTIVE_HEALTH = {"active", "active_information_only_policy"}
BLOCKED_AUTOMATION = {
    "owner_managed_product_disabled", "disabled", "quarantined",
    "suspended_or_inaccessible", "disabled_pending_platform_resolution",
}


@lru_cache(maxsize=1)
def load_serp_targets(path: str | Path | None = None) -> dict:
    target = Path(path) if path else TARGETS_PATH
    with target.open(encoding="utf-8") as handle:
        data = json.load(handle)
    required = {"objective", "queries", "property_roles", "aggressiveness"}
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError("SERP targets missing keys: " + ", ".join(missing))
    return data


def _host(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def _asset_id(asset: dict) -> str:
    return asset.get("id") or asset.get("platform") or _host(asset.get("url"))


def match_asset(url: str, assets: list[dict]) -> dict | None:
    """Match a result to the most specific registered asset URL/host."""
    result_host = _host(url)
    if not result_host:
        return None
    candidates = []
    for asset in assets:
        asset_url = asset.get("url")
        if not asset_url or _host(asset_url) != result_host:
            continue
        path = urlparse(asset_url).path.rstrip("/")
        candidates.append((len(path), asset))
    return max(candidates, default=(0, None), key=lambda item: item[0])[1]


def classify_result(result: dict, assets: list[dict]) -> dict:
    asset = match_asset(result.get("link") or result.get("url") or "", assets)
    sentiment = result.get("sentiment", "unknown")
    controlled = bool(asset and asset.get("controlled"))
    approved = bool(asset and asset.get("tier") in {"A", "B"})
    desired = bool(
        approved
        and asset.get("status") != "quarantined"
        and sentiment not in {"negative", "harmful"}
    )
    return {
        **result,
        "url": result.get("link") or result.get("url"),
        "asset_id": _asset_id(asset) if asset else None,
        "asset_type": asset.get("type") if asset else None,
        "controlled": controlled,
        "desired": desired,
        "sentiment": sentiment,
    }


def build_query_control_map(snapshot: dict, assets: list[dict]) -> dict:
    results = [
        classify_result({**result, "position": result.get("position", index)}, assets)
        for index, result in enumerate(snapshot.get("results", []), start=1)
        if int(result.get("position", index)) <= 10
    ]
    desired = [r for r in results if r["desired"]]
    controlled = [r for r in desired if r["controlled"]]
    negative = [r for r in results if r["sentiment"] in {"negative", "harmful"}]
    weighted_total = sum(RANK_WEIGHTS.get(r["position"], 0) for r in results) or 1
    weighted_desired = sum(RANK_WEIGHTS.get(r["position"], 0) for r in desired)
    return {
        "query": snapshot.get("query"),
        "country": snapshot.get("country", "IL"),
        "language": snapshot.get("language", "he"),
        "device": snapshot.get("device", "unknown"),
        "observed_at": snapshot.get("observed_at"),
        "results": results,
        "desired_count": len(desired),
        "controlled_count": len(controlled),
        "negative_count": len(negative),
        "unclassified_count": sum(r["sentiment"] == "unknown" for r in results),
        "weighted_desired_share": round(weighted_desired / weighted_total, 4),
        "controlled_positions": [r["position"] for r in controlled],
        "negative_positions": [r["position"] for r in negative],
    }


def _action(priority: str, kind: str, asset: dict | None, query: str, reason: str,
            actions: list[str], evidence: dict | None = None) -> dict:
    return {
        "priority": priority,
        "kind": kind,
        "asset_id": _asset_id(asset) if asset else None,
        "asset_url": asset.get("url") if asset else None,
        "query": query,
        "reason": reason,
        "actions": actions,
        "evidence": evidence or {},
        "status": "proposed",
        "approval_required": "medical_editor"
        if kind in {"publish_original", "refresh_content"} else "standard",
    }


def _ranked_asset(asset: dict, control_maps: list[dict]) -> tuple[int | None, str | None]:
    for control_map in control_maps:
        for result in control_map["results"]:
            if result.get("asset_id") == _asset_id(asset):
                return result["position"], control_map["query"]
    return None, None


def _asset_opportunities(assets: list[dict], control_maps: list[dict]) -> list[dict]:
    actions = []
    target_query = control_maps[0]["query"] if control_maps else "ד״ר גיא רופא"
    for asset in sorted(assets, key=lambda a: a.get("priority", 0), reverse=True):
        if not asset.get("controlled") or asset.get("tier") not in {"A", "B"}:
            continue
        if asset.get("status") == "quarantined" or asset.get("automation") in BLOCKED_AUTOMATION:
            continue
        position, query = _ranked_asset(asset, control_maps)
        health = asset.get("status", "")
        if "audit_required" in health or health.endswith("_required"):
            actions.append(_action(
                "P1", "asset_audit", asset, query or target_query,
                "A high-priority controlled asset cannot be pushed safely before its factual, canonical and content audit.",
                [
                    "Audit visible facts, title, biography, current status, canonical and indexability",
                    "Remove or noindex thin, duplicate or solicitation content",
                    "Assign a distinct query intent and editorial role",
                ],
                {"health_status": health},
            ))
        elif position is None:
            actions.append(_action(
                "P1", "activate_asset", asset, target_query,
                "Approved controlled asset is absent from the observed first page.",
                [
                    "Confirm crawlability, self-canonical, sitemap inclusion and index status",
                    "Publish or improve substantial platform-native identity content",
                    "Add one natural contextual link from a relevant stronger approved asset",
                    "Maintain the asset and measure branded-query movement weekly",
                ],
            ))
        elif position <= 3:
            actions.append(_action(
                "P2", "defend_asset", asset, query or target_query,
                f"Controlled asset already holds a defensive top-{position} result.",
                [
                    "Protect URL stability and factual accuracy",
                    "Refresh only when material value or facts change",
                    "Monitor title, snippet, sitelinks and displacement risk",
                ],
                {"position": position},
            ))
        else:
            actions.append(_action(
                "P1", "strengthen_asset", asset, query or target_query,
                f"Controlled asset is on page one at position {position} and can gain defensive weight.",
                [
                    "Improve the exact page that ranks rather than creating a duplicate",
                    "Close evidence, intent, title and internal-link gaps",
                    "Distribute a platform-native summary that links to the canonical article",
                ],
                {"position": position},
            ))
    return actions


def search_console_opportunities(rows: list[dict], assets: list[dict]) -> list[dict]:
    """Turn Search Console query/page rows into striking-distance work."""
    actions = []
    for row in rows:
        position = float(row.get("position", 100))
        impressions = float(row.get("impressions", 0))
        if not (3 < position <= 20 and impressions >= 10):
            continue
        page = row.get("page") or (row.get("keys") or [None, None])[-1]
        query = row.get("query") or (row.get("keys") or [None])[0]
        asset = match_asset(page or "", assets)
        if not asset or not asset.get("controlled"):
            continue
        actions.append(_action(
            "P1", "refresh_content", asset, query,
            f"Search Console shows a striking-distance page at average position {position:.1f}.",
            [
                "Preserve the ranking URL",
                "Improve the page for the observed query intent with original evidence",
                "Add relevant internal links and verify canonical/index status",
                "Compare 28-day clicks, impressions, CTR and position after the change",
            ],
            {"page": page, "position": position, "impressions": impressions},
        ))
    return actions


def evaluate_ai_visibility(snapshots: list[dict], approved_hosts: set[str]) -> dict:
    valid = [s for s in snapshots if s.get("status") != "error"]
    if not valid:
        return {
            "samples": 0, "factual_accuracy_rate": None,
            "official_citation_rate": None, "desired_citation_share": None,
        }
    accurate = sum(not s.get("factual_errors") and not s.get("identity_misinformation")
                   and not s.get("active_practice_claim") for s in valid)
    official = 0
    desired_citations = total_citations = 0
    for sample in valid:
        citations = sample.get("cited_sources") or []
        hosts = {_host(c) for c in citations if c}
        total_citations += len(hosts)
        desired_citations += len(hosts & approved_hosts)
        official += bool(sample.get("official_source_cited") or hosts & approved_hosts)
    return {
        "samples": len(valid),
        "factual_accuracy_rate": round(accurate / len(valid), 4),
        "official_citation_rate": round(official / len(valid), 4),
        "desired_citation_share": round(desired_citations / total_citations, 4)
        if total_citations else 0.0,
    }


def detect_cross_domain_risk(content_inventory: list[dict]) -> list[dict]:
    """Flag duplicate fingerprints or shared target intent across owned domains."""
    risks = []
    by_fingerprint: dict[str, list[dict]] = {}
    by_query: dict[str, list[dict]] = {}
    for item in content_inventory:
        if item.get("fingerprint"):
            by_fingerprint.setdefault(item["fingerprint"], []).append(item)
        if item.get("target_query"):
            by_query.setdefault(item["target_query"], []).append(item)
    for fingerprint, items in by_fingerprint.items():
        hosts = {_host(item.get("url")) for item in items}
        if len(hosts) > 1:
            risks.append({
                "type": "cross_domain_duplicate",
                "fingerprint": fingerprint,
                "urls": [item.get("url") for item in items],
                "required_action": "Choose one canonical owner or rewrite with a genuinely distinct purpose.",
            })
    for query, items in by_query.items():
        hosts = {_host(item.get("url")) for item in items}
        intents = {item.get("intent") for item in items}
        if len(hosts) > 1 and len(intents) <= 1:
            risks.append({
                "type": "query_cannibalization",
                "query": query,
                "urls": [item.get("url") for item in items],
                "required_action": "Assign distinct intents; do not make controlled domains clones.",
            })
    return risks


def propose_new_assets(
    assets: list[dict],
    control_maps: list[dict],
    content_inventory: list[dict] | None = None,
) -> list[dict]:
    """Propose creative assets only when they add a distinct, maintainable value."""
    targets = load_serp_targets()
    existing_types = {asset.get("type") for asset in assets if asset.get("status") != "quarantined"}
    weakest_map = min(
        control_maps,
        key=lambda item: (item["desired_count"], item["controlled_count"]),
        default=None,
    )
    if not weakest_map:
        return []
    gap = max(0, targets["objective"]["desired_results_target"] - weakest_map["desired_count"])
    if not gap:
        return []
    inventory_kinds = {item.get("kind") for item in (content_inventory or [])}
    proposals = []
    mappings = {
        "original_research_library": ("research_library", 10, 4),
        "named_medical_newsroom": ("official_site", 9, 5),
        "video_explainer_series": ("video_channel", 8, 6),
        "podcast_season": ("podcast_profile", 7, 5),
        "public_document_collection": ("document_profile", 7, 7),
        "newsletter_archive": ("newsletter_archive", 6, 6),
        "expert_qa_library": ("expert_qa_profile", 8, 7),
        "independent_editorial_opportunity": ("independent_media", 10, 4),
    }
    for candidate in targets.get("asset_creation_portfolio", []):
        kind = candidate["kind"]
        mapped_type, impact, speed = mappings[kind]
        if mapped_type in existing_types or kind in inventory_kinds:
            continue
        proposals.append({
            "priority": "P1" if impact >= 9 else "P2",
            "kind": "create_or_earn_new_asset",
            "asset_kind": kind,
            "query": weakest_map["query"],
            "reason": (
                f"The weakest observed brand SERP is short of the desired-result "
                f"target by {gap}; this asset adds a distinct retrieval surface."
            ),
            "surface": candidate["surface"],
            "value": candidate["value"],
            "minimum_proof": candidate["minimum_proof"],
            "impact": impact,
            "speed": speed,
            "approval_required": "owner",
            "status": "proposed",
            "kill_criteria": [
                "No distinct audience or query intent",
                "No sustainable maintenance owner",
                "Would duplicate an existing controlled property",
                "Would present controlled content as independent",
            ],
        })
    return sorted(
        proposals,
        key=lambda item: (0 if item["priority"] == "P1" else 1, -item["impact"], -item["speed"]),
    )


def evaluate_new_asset_hypothesis(hypothesis: dict) -> dict:
    """Critically approve, incubate or reject a proposed controlled asset."""
    positive_fields = {
        "distinct_audience": 15,
        "distinct_search_intent": 15,
        "original_content_inventory": 20,
        "maintenance_capacity_12m": 15,
        "brand_relevance": 10,
        "technical_ownership": 10,
        "realistic_authority_path": 15,
    }
    penalty_fields = {
        "duplicate_content_risk": 25,
        "fake_independence_risk": 40,
        "ymyl_review_gap": 30,
        "thin_inventory_risk": 20,
        "reputation_only_purpose": 35,
    }
    score = sum(weight for field, weight in positive_fields.items() if hypothesis.get(field))
    penalties = sum(weight for field, weight in penalty_fields.items() if hypothesis.get(field))
    score = max(0, min(100, score - penalties))
    gate = load_serp_targets()["new_asset_decision_gate"]
    if score >= gate["minimum_build_score"]:
        decision = "build"
    elif score >= gate["minimum_incubate_score"]:
        decision = "incubate"
    else:
        decision = "reject"
    missing = [field for field in positive_fields if not hypothesis.get(field)]
    risks = [field for field in penalty_fields if hypothesis.get(field)]
    return {
        "name": hypothesis.get("name"),
        "score": score,
        "decision": decision,
        "missing_proof": missing,
        "material_risks": risks,
        "next_step": gate["outcomes"][decision],
        "critical_note": (
            "A SERP gap alone never justifies a new asset. The asset must deserve to exist "
            "for users even if rankings do not improve."
        ),
    }


def orchestrate_reputation_cycle(
    assets: list[dict],
    serp_snapshots: list[dict],
    ai_snapshots: list[dict] | None = None,
    search_console_rows: list[dict] | None = None,
    content_inventory: list[dict] | None = None,
) -> dict:
    """Build one evidence-led, maximum-sustainable action cycle."""
    targets = load_serp_targets()
    control_maps = [build_query_control_map(snapshot, assets) for snapshot in serp_snapshots]
    approved_hosts = {
        _host(asset.get("url")) for asset in assets
        if asset.get("tier") in {"A", "B"} and asset.get("status") != "quarantined"
    }
    ai = evaluate_ai_visibility(ai_snapshots or [], approved_hosts)
    risks = detect_cross_domain_risk(content_inventory or [])
    actions = _asset_opportunities(assets, control_maps)
    actions.extend(search_console_opportunities(search_console_rows or [], assets))
    new_asset_proposals = propose_new_assets(assets, control_maps, content_inventory)
    for control_map in control_maps:
        if control_map["negative_count"]:
            actions.append(_action(
                "P1", "displacement_campaign", None, control_map["query"],
                f"{control_map['negative_count']} negative result(s) occupy page one.",
                [
                    "Preserve the result, position, query, locale and date",
                    "Check factual correction, platform policy and lawful removal eligibility",
                    "Strengthen the closest approved controlled assets with distinct useful content",
                    "Earn independent corroboration; never fabricate or mass-report",
                ],
                {"negative_positions": control_map["negative_positions"]},
            ))
    objective = targets["objective"]
    if ai["samples"] and (
        ai["factual_accuracy_rate"] < objective["ai_factual_accuracy_target"]
        or ai["official_citation_rate"] < objective["ai_official_citation_target"]
    ):
        actions.append(_action(
            "P1", "ai_visibility_correction", None, "AI answer prompts",
            "AI accuracy or approved-source citation is below target.",
            [
                "Identify repeated errors and cited source gaps across at least three samples",
                "Correct owned source facts and publish concise citable passages",
                "Confirm OAI-SearchBot and PerplexityBot crawl access",
                "Request re-indexing where supported and re-test until three clean checks",
            ],
            ai,
        ))
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    actions.sort(key=lambda action: (
        priority_order.get(action["priority"], 9),
        -int((action.get("evidence") or {}).get("impressions", 0)),
        action["kind"],
    ))
    return {
        "objective": (
            "Maximize approved desired and controlled page-one results and accurate "
            "approved-source visibility in AI answers."
        ),
        "mode": targets["aggressiveness"]["mode"],
        "guardrail": "Maximum sustainable execution without spam, deception, fake independence or medical solicitation.",
        "control_maps": control_maps,
        "ai_visibility": ai,
        "cross_domain_risks": risks,
        "new_asset_proposals": new_asset_proposals,
        "next_best_actions": actions,
        "targets": objective,
        "measurement": {
            "serp": "daily by exact query, country, language and device",
            "search_console": "weekly 28-day and prior-period comparison by query and page",
            "ai": "daily repeated samples; preserve exact answer and citations",
            "reprioritization": "weekly and immediately after a material negative result",
        },
    }
