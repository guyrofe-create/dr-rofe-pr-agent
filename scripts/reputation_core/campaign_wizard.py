"""P2 campaign-opening wizard: plain-language brief -> approved campaign files."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


SECTION_PATTERNS = {
    "queries": r"כאשר\s+מחפשים\s+(.+?)(?=,\s*אני\s+רוצה|\s+אני\s+רוצה)",
    "outcome": (
        r"אני\s+רוצה\s+ש(?:המשתמש|הגולש|המחפש)\s+"
        r"(?:יקבל|יראה|ימצא)\s+(.+?)(?=,\s*דרך\s+הנכסים|\s+דרך\s+הנכסים)"
    ),
    "assets": r"דרך\s+הנכסים\s+(.+?)(?=,\s*תוך\s+איסור|\s+תוך\s+איסור)",
    "prohibitions": r"תוך\s+איסור\s+על\s+(.+?)(?:[.!?]|$)",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip(" \t\n,.;:")


def _items(value: str) -> list[str]:
    """Split an explicit customer list without guessing inside normal prose."""
    urls: dict[str, str] = {}

    def protect_url(match: re.Match) -> str:
        placeholder = f"__CAMPAIGN_URL_{len(urls)}__"
        urls[placeholder] = match.group(0)
        return placeholder

    protected = re.sub(r"https?://[^\s,;]+", protect_url, value or "")
    parts = re.split(r"\s*(?:\s+/\s+|;|\n|,\s*)\s*", protected)
    restored = []
    for item in map(_clean, parts):
        for placeholder, url in urls.items():
            item = item.replace(placeholder, url)
        if item:
            restored.append(item)
    return list(dict.fromkeys(restored))


def parse_plain_language_brief(brief: str) -> dict:
    """Parse the product's documented X/Y/A-B-C/Z sentence contract."""
    normalized = _clean(brief)
    if not normalized:
        raise ValueError("campaign brief is empty")
    extracted = {}
    missing = []
    for key, pattern in SECTION_PATTERNS.items():
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            extracted[key] = _clean(match.group(1))
        else:
            missing.append(key)
    if missing:
        raise ValueError(
            "brief must state search terms, desired outcome, assets and "
            "prohibitions; missing: " + ", ".join(missing)
        )
    queries = _items(extracted["queries"])
    assets = _items(extracted["assets"])
    prohibitions = _items(extracted["prohibitions"])
    if not queries or not assets or not prohibitions:
        raise ValueError("queries, assets and prohibitions may not be empty")
    return {
        "brief": normalized,
        "primary_queries": queries[:1],
        "secondary_queries": queries[1:],
        "desired_outcome": extracted["outcome"],
        "desired_narratives": [extracted["outcome"]],
        "requested_assets": assets,
        "prohibitions": prohibitions,
        "proposed_facts": [],
    }


def _asset_aliases(asset: dict) -> set[str]:
    url = asset.get("url", "")
    host = urlparse(url).netloc.lower().removeprefix("www.")
    return {
        _clean(str(asset.get("platform", ""))).casefold(),
        _clean(str(asset.get("name", ""))).casefold(),
        _clean(url).casefold(),
        host,
    } - {""}


def resolve_requested_assets(
    requested: list[str],
    asset_registry: dict,
) -> list[dict]:
    resolved = []
    known = asset_registry.get("assets", [])
    for request in requested:
        folded = request.casefold()
        match = next(
            (
                asset for asset in known
                if folded in _asset_aliases(asset)
            ),
            None,
        )
        if match:
            resolved.append({
                "request": request,
                "status": "verified_existing",
                "platform": match.get("platform"),
                "url": match.get("url"),
                "controlled": bool(match.get("controlled")),
                "role": match.get("role") or match.get("type"),
            })
        else:
            url_match = re.search(r"https?://[^\s]+", request)
            resolved.append({
                "request": request,
                "status": "pending_ownership_verification",
                "platform": request if not url_match else urlparse(
                    url_match.group(0)
                ).netloc,
                "url": url_match.group(0).rstrip(".,)") if url_match else None,
                "controlled": False,
                "role": "proposed_campaign_asset",
            })
    return resolved


def _metric_set(
    primary_queries: list[str],
    secondary_queries: list[str],
    assets: list[dict],
    profile: dict,
) -> list[dict]:
    goal = profile["search_goal"]
    controlled_assets = sum(1 for asset in assets if asset.get("controlled"))
    return [
        {
            "id": "google_desired_page_one_results",
            "target": int(goal.get("desired_results_target", 7)),
            "scope": primary_queries,
            "measurement": "daily top-10 SERP snapshot by configured market/device",
        },
        {
            "id": "google_controlled_page_one_results",
            "target": min(
                int(goal.get("controlled_results_target", 5)),
                max(1, controlled_assets),
            ),
            "scope": primary_queries,
            "measurement": "verified controlled URLs in organic top 10",
        },
        {
            "id": "ai_factual_accuracy",
            "target": 1.0,
            "scope": primary_queries + secondary_queries,
            "measurement": "fact-registry grounded answer samples",
        },
        {
            "id": "ai_approved_source_citation_rate",
            "target": 0.8,
            "scope": primary_queries + secondary_queries,
            "measurement": "answers citing an approved A/B asset",
        },
        {
            "id": "content_safety_violations",
            "target": 0,
            "scope": ["all approved campaign outputs"],
            "measurement": "pre-publication policy gate and audit log",
        },
    ]


def build_campaign_draft(
    intake: dict,
    profile: dict,
    fact_registry: dict,
    asset_registry: dict,
) -> dict:
    """Translate customer intent into a complete, reviewable campaign draft."""
    primary = list(dict.fromkeys(intake.get("primary_queries", [])))
    secondary = list(dict.fromkeys(intake.get("secondary_queries", [])))
    if not primary:
        raise ValueError("campaign needs at least one primary query")
    outcome = _clean(intake.get("desired_outcome", ""))
    if not outcome:
        raise ValueError("campaign needs a desired outcome")
    requested = intake.get("requested_assets", [])
    if not requested:
        raise ValueError("campaign needs at least one requested asset")
    prohibitions = list(dict.fromkeys(intake.get("prohibitions", [])))
    if not prohibitions:
        raise ValueError("campaign needs at least one explicit prohibition")

    assets = resolve_requested_assets(requested, asset_registry)
    approved_facts = [
        {
            "field": fact["field"],
            "value": fact["value"],
            "evidence": fact.get("evidence", []),
        }
        for fact in fact_registry.get("facts", [])
        if fact.get("status") == "approved" and fact.get("public")
    ]
    proposed_facts = [
        {
            **fact,
            "status": "pending_evidence_and_owner_approval",
        }
        for fact in intake.get("proposed_facts", [])
    ]
    approval = copy.deepcopy(profile["approval_policy"])
    approval["campaign_activation_required"] = True
    approval["new_or_changed_fact_required"] = True
    approval["unverified_asset_required"] = True
    approval["public_publication_required"] = True
    approval["drafting_autonomous"] = True

    draft = {
        "version": 2,
        "kind": "campaign_opening_draft",
        "client_id": profile["client_id"],
        "created_at": _now(),
        "status": "awaiting_customer_approval",
        "source_brief": intake.get("brief", ""),
        "plain_language_goal": {
            "when_searching": primary + secondary,
            "desired_outcome": outcome,
            "through_assets": requested,
            "prohibited": prohibitions,
        },
        "queries": {
            "primary": [
                {"query": query, "priority": max(80, 100 - index * 5)}
                for index, query in enumerate(primary)
            ],
            "secondary": [
                {"query": query, "priority": max(50, 75 - index * 5)}
                for index, query in enumerate(secondary)
            ],
        },
        "desired_knowledge": {
            "approved_facts": approved_facts,
            "proposed_facts": proposed_facts,
            "desired_narratives": list(dict.fromkeys(
                intake.get("desired_narratives", []) or [outcome]
            )),
            "rule": (
                "Narratives guide emphasis. Only evidence-backed approved facts "
                "may be stated as facts."
            ),
        },
        "targets": {
            "google": {
                "market": profile["market"],
                "desired_page_one_results": int(
                    profile["search_goal"].get("desired_results_target", 7)
                ),
                "controlled_page_one_results": int(
                    profile["search_goal"].get("controlled_results_target", 5)
                ),
                "negative_page_one_results": 0,
            },
            "ai": {
                "factual_accuracy": 1.0,
                "approved_source_citation_rate": 0.8,
                "misidentification_rate": 0.0,
                "monitoring_prompts": [
                    f"מה ידוע ממקורות אמינים על {query}?"
                    for query in primary + secondary
                ],
            },
        },
        "assets": assets,
        "approval_rules": approval,
        "content_constraints": {
            "customer_prohibitions": prohibitions,
            "installation_guardrails": profile.get(
                "publication_guardrails", {}
            ),
            "no_unapproved_facts": True,
            "no_publication_without_item_approval": True,
            "no_doorway_or_scaled_thin_content": True,
        },
        "success_metrics": _metric_set(
            primary, secondary, assets, profile
        ),
        "activation_preconditions": [
            "customer approves this exact campaign draft",
            "every proposed fact is either evidence-approved or excluded",
            "ownership and publication rights are verified for requested assets",
            "baseline Google and AI measurements are collected",
        ],
    }
    draft["approval_id"] = campaign_approval_id(draft)
    return draft


def campaign_approval_id(draft: dict) -> str:
    material = copy.deepcopy(draft)
    material.pop("approval_id", None)
    material.pop("created_at", None)
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "campaign-" + hashlib.sha256(encoded).hexdigest()[:16]


def validate_campaign_draft(draft: dict) -> None:
    required = {
        "version", "client_id", "status", "plain_language_goal", "queries",
        "desired_knowledge", "targets", "assets", "approval_rules",
        "content_constraints", "success_metrics", "approval_id",
    }
    missing = sorted(required - draft.keys())
    if missing:
        raise ValueError("campaign draft missing: " + ", ".join(missing))
    if draft["status"] != "awaiting_customer_approval":
        raise ValueError("only an awaiting-customer-approval draft may activate")
    if not draft["queries"]["primary"]:
        raise ValueError("campaign draft has no primary queries")
    if not draft["approval_rules"].get("public_publication_required"):
        raise ValueError("campaign may not disable publication approval")
    if draft["approval_id"] != campaign_approval_id(draft):
        raise ValueError("campaign approval id does not match draft contents")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_json_transaction(updates: list[tuple[Path, dict]]) -> None:
    """Apply a group of JSON updates and restore every file if one write fails."""
    originals = {
        path: path.read_bytes() if path.exists() else None
        for path, _payload in updates
    }
    try:
        for path, payload in updates:
            _write_json(path, payload)
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(original)
        raise


def apply_approved_campaign(
    root: Path,
    draft: dict,
    approval_id: str,
) -> dict:
    """Atomically project an approved P2 draft into runtime configuration."""
    validate_campaign_draft(draft)
    if approval_id != draft["approval_id"]:
        raise ValueError("explicit approval id does not match campaign draft")
    config = root / "config"
    data = root / "data"
    profile_path = config / "client_profile.json"
    targets_path = config / "serp_targets.json"
    strategy_path = config / "reputation_strategy.json"
    facts_path = data / "fact_registry.json"
    assets_path = data / "asset_registry.json"
    required_paths = [
        profile_path, targets_path, strategy_path, facts_path, assets_path,
    ]
    if any(not path.exists() for path in required_paths):
        raise FileNotFoundError("installation is incomplete; run P1 setup first")

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    targets = json.loads(targets_path.read_text(encoding="utf-8"))
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    assets = json.loads(assets_path.read_text(encoding="utf-8"))
    if profile["client_id"] != draft["client_id"]:
        raise ValueError("campaign belongs to a different installation")

    query_items = draft["queries"]["primary"] + draft["queries"]["secondary"]
    profile["search_goal"]["primary_queries"] = draft["queries"]["primary"]
    profile["search_goal"]["secondary_queries"] = draft["queries"]["secondary"]
    profile["search_goal"]["statement"] = draft[
        "plain_language_goal"
    ]["desired_outcome"]
    profile["desired_narratives"] = draft[
        "desired_knowledge"
    ]["desired_narratives"]
    profile["approval_policy"] = draft["approval_rules"]
    profile["campaign_content_constraints"] = draft["content_constraints"]
    profile["campaign_success_metrics"] = draft["success_metrics"]
    profile.setdefault("ai_evaluation", {})["monitoring_prompts"] = draft[
        "targets"
    ]["ai"]["monitoring_prompts"]

    targets["queries"] = [
        {
            "query": item["query"],
            "kind": (
                "primary"
                if item in draft["queries"]["primary"]
                else "secondary"
            ),
            "priority": item["priority"],
        }
        for item in query_items
    ]
    targets["objective"].update({
        "desired_results_target": draft["targets"]["google"][
            "desired_page_one_results"
        ],
        "controlled_results_target": draft["targets"]["google"][
            "controlled_page_one_results"
        ],
        "negative_results_target": 0,
        "ai_factual_accuracy_target": draft["targets"]["ai"][
            "factual_accuracy"
        ],
        "ai_official_citation_target": draft["targets"]["ai"][
            "approved_source_citation_rate"
        ],
    })
    strategy["objective"] = profile["search_goal"]["statement"]
    strategy["success_metrics"] = [
        metric["id"] for metric in draft["success_metrics"]
    ]
    strategy.setdefault("ai_monitoring", {})["prompts"] = draft[
        "targets"
    ]["ai"]["monitoring_prompts"]

    known_urls = {asset.get("url") for asset in assets.get("assets", [])}
    for requested in draft["assets"]:
        if requested.get("url") and requested["url"] not in known_urls:
            assets.setdefault("assets", []).append({
                "platform": requested.get("platform"),
                "url": requested["url"],
                "type": requested.get("role"),
                "tier": "C",
                "status": "ownership_verification_required",
                "controlled": False,
                "priority": 40,
            })
            known_urls.add(requested["url"])

    approved_fields = {fact.get("field") for fact in facts.get("facts", [])}
    for proposed in draft["desired_knowledge"]["proposed_facts"]:
        if proposed.get("status") != "approved" or not proposed.get("evidence"):
            continue
        if proposed.get("field") not in approved_fields:
            facts.setdefault("facts", []).append(proposed)
            approved_fields.add(proposed.get("field"))

    activated = copy.deepcopy(draft)
    activated["status"] = "active_awaiting_baseline"
    activated["approved_at"] = _now()
    activated["approved_with"] = approval_id
    activated["next_actions"] = [
        "collect Google baseline",
        "collect AI-answer baseline",
        "verify pending asset ownership",
        "prepare first item-level approval bundle",
    ]
    _write_json_transaction([
        (profile_path, profile),
        (targets_path, targets),
        (strategy_path, strategy),
        (facts_path, facts),
        (assets_path, assets),
        (data / "campaign_plan.json", activated),
    ])
    return activated
