"""Single-tenant installation wizard and preflight validation."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def validate_install_spec(spec: dict) -> None:
    required = {
        "client_id", "display_name", "canonical_site", "current_role",
        "primary_queries", "market", "sites", "assets",
    }
    missing = sorted(required - spec.keys())
    if missing:
        raise ValueError("installation spec missing: " + ", ".join(missing))
    if not spec["primary_queries"]:
        raise ValueError("at least one primary query is required")
    if urlparse(spec["canonical_site"]).scheme != "https":
        raise ValueError("canonical_site must use HTTPS")
    if not any(site.get("canonical") for site in spec["sites"]):
        raise ValueError("one site must be marked canonical")
    if len([site for site in spec["sites"] if site.get("canonical")]) != 1:
        raise ValueError("exactly one canonical site is required")


def build_installation_files(spec: dict, base_strategy: dict) -> dict[str, dict]:
    """Return all client-specific JSON documents without writing secrets."""
    validate_install_spec(spec)
    now = datetime.now(timezone.utc).isoformat()
    name_variants = list(dict.fromkeys(
        [spec["display_name"]] + spec.get("name_variants", [])
    ))
    primary_queries = [
        {"query": query, "priority": max(60, 100 - index * 5)}
        for index, query in enumerate(spec["primary_queries"])
    ]
    approval = {
        "public_publication_required": True,
        "medical_review_required": bool(spec.get("medical_content", False)),
        "new_account_or_domain_required": True,
        "legal_action_required": True,
        "external_outreach_required": True,
        "single_exact_approval_bundle_required": True,
        "signed_material_payload_required": True,
        "any_material_edit_invalidates_approval": True,
        "idempotent_execution_required": True,
        "public_url_and_receipt_required": True,
        "read_only_monitoring_autonomous": True,
        "drafting_autonomous": True,
    }
    asset_policy = {
        "mode": "maximum_sustainable",
        "minimum_build_score": 75,
        "minimum_distinct_purpose_score": 80,
        "minimum_maintenance_health": 0.8,
        "minimum_content_runway_items": 12,
        "maximum_allowed_content_similarity": 0.65,
        "require_all_p5_mandatory_proofs": True,
        "maintenance_capacity_units": float(
            spec.get("maintenance_capacity_units", 0)
        ),
        "default_asset_maintenance_units": 1,
        "new_asset_maintenance_units": 1,
        "incubate_new_concepts_inside_existing_asset_first": True,
        "hard_stop_signals": [
            "fake_independence", "duplicate_intent", "cloned_content",
            "doorway_pattern", "thin_content", "unmaintained_assets",
            "manual_action", "indexing_anomaly", "cannibalization",
        ],
    }
    asset_policy.update(spec.get("asset_policy", {}))
    canonical_facts = {
        "primary_name": spec["display_name"],
        "name_variants": name_variants,
        "canonical_site": spec["canonical_site"],
        "current_role": spec["current_role"],
        "practice_status": spec.get("practice_status", "not_applicable"),
        "public_status_he": spec.get("public_status", ""),
        "allowed_cta_he": spec.get(
            "allowed_cta", f"למידע נוסף: {spec['canonical_site']}"
        ),
        "facts_require_evidence": True,
        "homepage_change_prohibited": bool(spec.get("homepage_change_prohibited", False)),
    }
    channel_policy = {
        "product_managed": spec.get("product_managed_channels", []),
        "owner_managed_product_disabled": spec.get("owner_managed_channels", []),
        "disabled": spec.get("disabled_channels", []),
        "deferred_until_unique_use": spec.get("deferred_channels", []),
    }
    monitoring_prompts = spec.get("ai_monitoring_prompts") or [
        f"מי הוא {spec['display_name']}?",
        f"מהו האתר הרשמי של {spec['display_name']}?",
        f"מה ידוע ממקורות אמינים על {spec['display_name']}?",
    ]
    profile = {
        "version": 1,
        "client_id": spec["client_id"],
        "display_name": spec["display_name"],
        "deployment_mode": "single_tenant",
        "market": spec["market"],
        "search_goal": {
            "statement": spec.get(
                "goal_statement",
                "Maximize accurate, desired and independently valuable search and AI visibility.",
            ),
            "primary_queries": primary_queries,
            "measurement_variants": spec.get("measurement_variants", []),
            "desired_results_target": int(spec.get("desired_results_target", 7)),
            "controlled_results_target": int(spec.get("controlled_results_target", 5)),
            "negative_results_target": 0,
        },
        "canonical_facts": canonical_facts,
        "channel_policy": channel_policy,
        "content_plan": {
            "language": spec["market"].get("language", "en"),
            "vertical": spec.get("content_vertical", "general_reputation"),
            "medical_content": bool(spec.get("medical_content", False)),
            "topics": spec.get("content_topics", []),
            "tags": spec.get("content_tags", []),
        },
        "publication_guardrails": spec.get("publication_guardrails", {
            "prohibited_solicitation_phrases": [],
            "prohibited_current_status_phrases": [],
            "visual_exclusions": [],
        }),
        "approval_policy": approval,
        "entity_seo": {
            "profile_page_required": True,
            "article_author_link_required": True,
            "platform_native_variants_required": True,
            "direct_answer_first": True,
            "tables_only_when_useful": True,
            "faq_only_when_useful": True,
            "primary_sources_preferred": True,
            "original_analysis_labeled": True,
            "image_visual_description_required": True,
            "entity_name_in_alt_only_when_relevant": True,
            "video_transcript_required": True,
            "search_crawlers": [
                "Googlebot", "Bingbot", "OAI-SearchBot", "PerplexityBot"
            ],
            "crawler_access_does_not_guarantee_visibility": True,
        },
        "opportunity_policy": spec.get("opportunity_policy", {
            "minimum_score": 20,
            "maximum_selected_per_cycle": 5,
            "maximum_per_asset": 2,
            "maximum_risk": 6,
            "maximum_high_risk_per_cycle": 1,
            "high_risk_starts_at": 5,
            "fixed_publication_days_determine_priority": False,
            "preparation_autonomous": True,
            "public_execution_requires_item_approval": True,
        }),
        "ai_evaluation": {
            "monitoring_prompts": monitoring_prompts,
            "prompt_rules": spec.get("ai_prompt_rules", []),
            "identity_conflict_markers": spec.get("identity_conflict_markers", []),
            "claim_conflict_markers": spec.get("claim_conflict_markers", []),
        },
        "asset_policy": asset_policy,
    }
    fact_fields = {
        "primary_name": spec["display_name"],
        "name_variants": name_variants,
        "canonical_site": spec["canonical_site"],
        "current_role": spec["current_role"],
        "practice_status": spec.get("practice_status", "not_applicable"),
    }
    facts = []
    for field, value in fact_fields.items():
        facts.append({
            "id": f"identity_{field}",
            "subject": spec["display_name"],
            "field": field,
            "value": value,
            "display_value": (
                spec.get("public_status")
                if field == "practice_status" and spec.get("public_status")
                else None
            ),
            "status": "approved",
            "public": True,
            "evidence": spec.get("fact_evidence", {}).get(
                field, [{"type": "installation_owner_approval", "at": now}]
            ),
        })
    fact_registry = {
        "version": 1,
        "updated_at": now,
        "policy": "Only approved facts may be used publicly.",
        "facts": facts,
        "unknowns": spec.get("unknown_facts", []),
    }
    assets = {"version": 1, "updated_at": now, "assets": spec["assets"]}
    property_roles = {}
    for site in spec["sites"]:
        host = urlparse(site["url"]).netloc.removeprefix("www.")
        property_roles[host] = {
            "role": site.get("role", "controlled_property"),
            "canonical": bool(site.get("canonical")),
            "platform": site.get("platform", "wordpress"),
        }
    serp_targets = {
        "version": 3,
        "objective": {
            "desired_results_target": profile["search_goal"]["desired_results_target"],
            "controlled_results_target": profile["search_goal"]["controlled_results_target"],
            "negative_results_target": 0,
            "ai_factual_accuracy_target": 1.0,
            "ai_official_citation_target": 0.8,
            "ai_identity_accuracy_target": 1.0,
            "ai_narrative_coverage_target": 0.8,
            "ai_source_diversity_target": 2,
            "ai_harmful_or_incorrect_target": 0.0,
            "ai_cross_sample_stability_target": 0.8,
        },
        "measurement_plan": {
            "search_engines": ["google", "bing"],
            "serp_surfaces": ["web_search"],
            "rank_weight": "reciprocal_rank",
            "volatility_windows_days": [7, 28],
            "ai_surfaces": [
                {
                    "engine": "OpenAI",
                    "surface": "responses_web_search",
                    "interface": "api",
                    "collection_method": "openai_responses_api",
                },
                {
                    "engine": "OpenAI",
                    "surface": "chatgpt_search",
                    "interface": "consumer_ui",
                    "collection_method": "authorized_browser_sample",
                },
                {
                    "engine": "Bing",
                    "surface": "ai_performance",
                    "interface": "bing_webmaster_tools_consumer_ui",
                    "collection_method": "authorized_manual_export",
                },
            ],
            "do_not_blend_dimensions": [
                "engine", "surface", "interface", "collection_method",
                "query_or_prompt", "country", "language", "device_or_model",
            ],
        },
        "queries": [
            {"query": item["query"], "kind": "primary", "priority": item["priority"]}
            for item in primary_queries
        ],
        "property_roles": property_roles,
        "aggressiveness": {
            "mode": "maximum_sustainable",
            "rule": "Maximize coverage only while every asset has independent value.",
        },
        "new_asset_decision_gate": {
            "minimum_build_score": asset_policy["minimum_build_score"],
            "minimum_incubate_score": 50,
            "outcomes": {
                "build": "Build only after owner approval and proof of maintenance.",
                "incubate": "Test inside an existing property first.",
                "reject": "Do not create the asset.",
            },
        },
        "asset_creation_portfolio": [],
    }
    strategy = copy.deepcopy(base_strategy)
    strategy["canonical_facts"] = canonical_facts
    strategy["channel_policy"] = channel_policy
    strategy["objective"] = profile["search_goal"]["statement"]
    strategy.setdefault("ai_monitoring", {})["prompts"] = monitoring_prompts
    medical = bool(spec.get("medical_content", False))
    strategy.setdefault("content_policy", {})[
        "medical_review_required_before_publication"
    ] = medical
    strategy["content_policy"][
        "sources_section_required_for_medical_articles"
    ] = medical
    connections = []
    for connection in spec.get("connections", []):
        connections.append({
            "platform": connection["platform"],
            "mode": connection.get("mode", "api"),
            "required": connection.get("required_secret_names", []),
            "currently_present": [],
            "status": "missing_tokens",
        })
    secret_manifest = {
        "version": 1,
        "client_id": spec["client_id"],
        "policy": (
            "Secret values live only in this installation's secret store. "
            "This manifest stores names, never values."
        ),
        "connections": connections,
    }
    campaign = {
        "version": 1,
        "client_id": spec["client_id"],
        "created_at": now,
        "status": "awaiting_first_measurement",
        "queries": primary_queries,
        "objectives": {
            "desired_page_one_results": profile["search_goal"]["desired_results_target"],
            "controlled_page_one_results": profile["search_goal"]["controlled_results_target"],
            "accurate_ai_answers": True,
        },
        "guardrails": asset_policy,
        "first_actions": [
            "Validate approved facts and active asset ownership",
            "Collect a complete SERP and AI baseline",
            "Audit canonical/indexation and assign each asset a distinct role",
            "Prepare, but do not publish, the first approval bundle",
        ],
    }
    business_profile = {
        "client_id": spec["client_id"],
        "name": spec["display_name"],
        "alternateName": name_variants[1:],
        "jobTitle": spec["current_role"],
        "description": spec.get("description", ""),
        "practiceStatus": spec.get("practice_status", "not_applicable"),
        "practiceStatusText": spec.get("practice_status_text", ""),
        "primaryLanguage": spec["market"].get("language", "en"),
        "profilePageUrl": (
            spec.get("profile_page_url")
            or spec["canonical_site"].rstrip("/") + "/profile/"
        ),
        "sites": spec["sites"],
        "sameAs": [
            asset["url"] for asset in spec["assets"] if asset.get("url")
        ],
    }
    return {
        "config/client_profile.json": profile,
        "config/reputation_strategy.json": strategy,
        "config/serp_targets.json": serp_targets,
        "config/secrets_manifest.json": secret_manifest,
        "data/fact_registry.json": fact_registry,
        "data/asset_registry.json": assets,
        "data/business_profile.json": business_profile,
        "data/campaign_plan.json": campaign,
        "data/reputation_history.json": {"version": 1, "snapshots": []},
        "data/bing_ai_performance.json": {
            "version": 1,
            "engine": "Bing",
            "surface": "ai_performance",
            "interface": "bing_webmaster_tools_consumer_ui",
            "collection_method": "authorized_manual_export",
            "period": {"start": None, "end": None},
            "rows": [],
        },
        "data/command_center.json": {
            "version": 1, "events": [], "crisis_rooms": [], "audit_log": [],
            "campaigns": [], "visibility_measurements": [],
            "opportunities": [],
            "asset_candidates": [],
        },
    }


def write_installation(
    destination: Path,
    files: dict[str, dict],
    *,
    force: bool = False,
) -> list[Path]:
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()) and not force:
        raise FileExistsError("destination is not empty; use --force explicitly")
    written = []
    for relative, payload in files.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(target)
    return written


def validate_installation_files(root: Path) -> dict:
    required = [
        "config/client_profile.json", "config/reputation_strategy.json",
        "config/serp_targets.json", "config/secrets_manifest.json",
        "data/fact_registry.json", "data/asset_registry.json",
        "data/campaign_plan.json",
    ]
    missing = [path for path in required if not (root / path).exists()]
    profiles = list((root / "config").glob("client_profile*.json"))
    errors = []
    if missing:
        errors.append("missing files: " + ", ".join(missing))
    if len(profiles) != 1 or profiles[0].name != "client_profile.json":
        errors.append("installation must contain exactly one client_profile.json")
    return {"status": "ready" if not errors else "blocked", "errors": errors}
