"""P5 creative, evidence-gated reputation asset planning."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from .asset_safety import evaluate_asset_candidate


MANDATORY_PROOFS = (
    "separate_system_purpose",
    "real_reader_value",
    "sustainable_maintenance",
    "reasonable_ranking_path",
    "no_duplication_or_doorway",
)


ASSET_ARCHETYPES = {
    "authoritative_profile": {
        "label": "Profile on an authoritative platform",
        "legacy_kind": "authority_profile",
        "asset_type": "authority_profile",
        "delivery_mode": "third_party_profile",
        "impact": 8,
        "authority": 9,
        "speed": 8,
        "maintenance_units": 0.5,
        "surfaces": ["Google", "Bing", "AI entity retrieval"],
        "purpose": (
            "A complete platform-native identity profile with verified facts, "
            "original activity and a link to the canonical source."
        ),
        "reader_value": (
            "Give users of that platform a useful, current identity record and "
            "native material unavailable as a copied biography."
        ),
        "minimum_original_items": 4,
        "existing_types": {
            "authority_profile", "professional_profile", "linkedin_profile",
        },
    },
    "youtube_or_video_series": {
        "label": "YouTube channel or video series",
        "legacy_kind": "video_explainer_series",
        "asset_type": "video_channel",
        "delivery_mode": "channel_or_series",
        "impact": 8,
        "authority": 9,
        "speed": 6,
        "maintenance_units": 1,
        "surfaces": ["Google video", "YouTube", "AI multimodal retrieval"],
        "purpose": (
            "A coherent video series that explains recurring topics with "
            "accessible transcripts, sources and a stable editorial format."
        ),
        "reader_value": (
            "Serve people who prefer concise audiovisual explanations and "
            "searchable transcripts rather than duplicate written articles."
        ),
        "minimum_original_items": 6,
        "existing_types": {"video_channel", "youtube_channel"},
    },
    "knowledge_library_or_hub": {
        "label": "Article library or knowledge hub",
        "legacy_kind": "original_research_library",
        "asset_type": "research_library",
        "delivery_mode": "section_or_existing_property",
        "impact": 9,
        "authority": 8,
        "speed": 6,
        "maintenance_units": 1,
        "surfaces": ["Google", "Bing", "Google AI", "AI answer engines"],
        "purpose": (
            "An organized, citable collection of original articles, evidence "
            "summaries, datasets or structured answers around one distinct intent."
        ),
        "reader_value": (
            "Help readers retrieve reviewed evidence and direct answers from a "
            "maintained taxonomy instead of scattered or repeated posts."
        ),
        "minimum_original_items": 12,
        "existing_types": {"research_library", "knowledge_hub"},
    },
    "books_apps_research_projects_page": {
        "label": "Books, apps, research or projects page",
        "legacy_kind": "project_portfolio_page",
        "asset_type": "project_portfolio_page",
        "delivery_mode": "page_on_existing_property",
        "impact": 7,
        "authority": 8,
        "speed": 9,
        "maintenance_units": 0.25,
        "surfaces": ["Google", "Bing", "AI entity and project retrieval"],
        "purpose": (
            "A first-party portfolio page that documents real books, apps, "
            "research or projects with verifiable identifiers and source links."
        ),
        "reader_value": (
            "Let readers verify and explore genuine work from one structured page "
            "instead of inferring it from promotional fragments."
        ),
        "minimum_original_items": 3,
        "existing_types": {"project_portfolio_page", "books_or_projects_page"},
    },
    "standalone_system_asset": {
        "label": "Standalone site with an independent systemic purpose",
        "legacy_kind": "standalone_system_site",
        "asset_type": "standalone_site",
        "delivery_mode": "standalone_site",
        "impact": 8,
        "authority": 4,
        "speed": 3,
        "maintenance_units": 2,
        "surfaces": ["Google", "Bing", "AI answer engines"],
        "purpose": (
            "A standalone publication or tool that serves a distinct audience and "
            "systemic use case even if it never changes a branded search result."
        ),
        "reader_value": (
            "Deliver an independent product, dataset, utility or editorial service "
            "that cannot be served coherently as a section of an existing property."
        ),
        "minimum_original_items": 12,
        "existing_types": {"standalone_site", "independent_publication"},
        "standalone": True,
    },
    "earned_article_interview_or_research": {
        "label": "Guest article, interview or data-led research",
        "legacy_kind": "earned_authority_contribution",
        "asset_type": "earned_media",
        "delivery_mode": "independent_earned_placement",
        "impact": 10,
        "authority": 9,
        "speed": 5,
        "maintenance_units": 0.25,
        "surfaces": ["Google", "News", "Google AI", "AI answer engines"],
        "purpose": (
            "A genuinely editorial contribution, interview or original study on an "
            "independent relevant publisher."
        ),
        "reader_value": (
            "Contribute useful expertise, evidence or original data to the "
            "publisher's audience without buying links or simulating independence."
        ),
        "minimum_original_items": 1,
        "existing_types": set(),
        "earned": True,
    },
    "wikipedia_wikidata_workstream": {
        "label": "Wikipedia/Wikidata eligibility and requested-edit workstream",
        "legacy_kind": "wikimedia_entity_workstream",
        "asset_type": "independent_knowledge_graph",
        "delivery_mode": "independent_requested_edit_workstream",
        "impact": 10,
        "authority": 10,
        "speed": 2,
        "maintenance_units": 0.25,
        "surfaces": ["Wikipedia", "Wikidata", "Knowledge Graph", "AI retrieval"],
        "purpose": (
            "Audit independent notability and propose neutral, sourced corrections "
            "through conflict-of-interest-safe Wikimedia processes."
        ),
        "reader_value": (
            "Improve the accuracy and verifiability of an independently governed "
            "knowledge record without treating it as a controlled marketing asset."
        ),
        "minimum_original_items": 2,
        "existing_types": {"wikipedia_article", "wikidata_item"},
        "earned": True,
        "wikimedia": True,
    },
}


def _proof(
    proof_id: str,
    passed: bool,
    *,
    evidence: list | None = None,
    missing: list | None = None,
    failed: list | None = None,
) -> dict:
    if failed:
        status = "fail"
    elif passed:
        status = "pass"
    else:
        status = "needs_evidence"
    return {
        "id": proof_id,
        "status": status,
        "evidence": evidence or [],
        "missing": missing or [],
        "failed": failed or [],
    }


def evaluate_creative_asset_candidate(
    candidate: dict,
    existing_assets: list[dict],
    creation_history: list[dict],
    policy: dict,
) -> dict:
    """Require five explicit proofs before a new asset can reach build."""
    evidence = candidate.get("proof_evidence") or {}
    risk_signals = set(candidate.get("risk_signals") or [])
    hard_stops = risk_signals & set(policy.get("hard_stop_signals", []))
    runway = evidence.get("original_content_plan") or []
    required_items = int(candidate.get("minimum_original_items", 1))

    purpose_pass = bool(
        evidence.get("purpose_verified")
        and evidence.get("distinct_audience")
        and evidence.get("distinct_intent")
        and evidence.get("purpose_statement")
    )
    purpose_missing = [
        "verified purpose statement",
        "distinct audience",
        "distinct query or user intent",
    ]
    if candidate.get("standalone"):
        purpose_pass = bool(
            purpose_pass
            and evidence.get("valuable_without_reputation_benefit")
            and evidence.get("cannot_fit_existing_asset")
        )
        purpose_missing.extend([
            "proof the asset remains valuable without reputation benefit",
            "proof the purpose cannot be served on an existing asset",
        ])
    if candidate.get("earned"):
        purpose_pass = bool(
            purpose_pass and evidence.get("editorial_independence_verified")
        )
        purpose_missing.append("verified editorial independence")
    if candidate.get("wikimedia"):
        purpose_pass = bool(
            purpose_pass
            and evidence.get("independent_notability_sources_verified")
            and evidence.get("conflict_of_interest_disclosure_planned")
            and evidence.get("requested_edit_route")
        )
        purpose_missing.extend([
            "independent reliable sources establishing notability",
            "conflict-of-interest disclosure plan",
            "talk-page or requested-edit route",
        ])
    value_pass = bool(
        evidence.get("reader_value_verified")
        and evidence.get("reader_value_statement")
        and len(runway) >= required_items
    )
    maintenance_pass = bool(
        evidence.get("maintenance_owner")
        and evidence.get("maintenance_schedule")
        and int(evidence.get("maintenance_months", 0)) >= 12
        and evidence.get("capacity_verified")
    )
    ranking_pass = bool(
        evidence.get("authority_path")
        and evidence.get("query_surface_fit")
        and evidence.get("index_or_discovery_path")
        and evidence.get("measurement_plan")
    )
    duplication_failures = sorted(hard_stops)
    maximum_allowed_similarity = float(
        policy.get("maximum_allowed_content_similarity", 0.65)
    )
    no_duplication_pass = bool(
        evidence.get("duplication_review_completed")
        and evidence.get("doorway_review_completed")
        and float(evidence.get("maximum_content_similarity", 1))
        < maximum_allowed_similarity
        and not duplication_failures
    )
    proofs = {
        "separate_system_purpose": _proof(
            "separate_system_purpose",
            purpose_pass,
            evidence=[
                evidence.get("purpose_statement"),
                evidence.get("distinct_audience"),
                evidence.get("distinct_intent"),
            ] if purpose_pass else [],
            missing=[] if purpose_pass else purpose_missing,
        ),
        "real_reader_value": _proof(
            "real_reader_value",
            value_pass,
            evidence=[
                evidence.get("reader_value_statement"),
                {"original_content_items": len(runway)},
            ] if value_pass else [],
            missing=[] if value_pass else [
                "verified reader-value statement",
                f"at least {required_items} original content or product items",
            ],
        ),
        "sustainable_maintenance": _proof(
            "sustainable_maintenance",
            maintenance_pass,
            evidence=[{
                "owner": evidence.get("maintenance_owner"),
                "schedule": evidence.get("maintenance_schedule"),
                "months": evidence.get("maintenance_months"),
            }] if maintenance_pass else [],
            missing=[] if maintenance_pass else [
                "accountable owner",
                "maintenance schedule",
                "verified capacity for at least 12 months",
            ],
        ),
        "reasonable_ranking_path": _proof(
            "reasonable_ranking_path",
            ranking_pass,
            evidence=[{
                "authority_path": evidence.get("authority_path"),
                "query_surface_fit": evidence.get("query_surface_fit"),
                "discovery": evidence.get("index_or_discovery_path"),
                "measurement": evidence.get("measurement_plan"),
            }] if ranking_pass else [],
            missing=[] if ranking_pass else [
                "realistic authority path",
                "query-to-surface fit",
                "index or discovery path",
                "measurement plan",
            ],
        ),
        "no_duplication_or_doorway": _proof(
            "no_duplication_or_doorway",
            no_duplication_pass,
            evidence=[{
                "maximum_content_similarity": evidence.get(
                    "maximum_content_similarity"
                ),
                "duplication_review": True,
                "doorway_review": True,
            }] if no_duplication_pass else [],
            missing=[] if no_duplication_pass or duplication_failures else [
                "cross-asset duplication review",
                "doorway-pattern review",
                (
                    "measured maximum content similarity below "
                    f"{maximum_allowed_similarity}"
                ),
            ],
            failed=duplication_failures,
        ),
    }
    failed = [
        proof_id for proof_id, result in proofs.items()
        if result["status"] == "fail"
    ]
    missing = [
        proof_id for proof_id, result in proofs.items()
        if result["status"] == "needs_evidence"
    ]
    safety = None
    if failed:
        outcome = "reject"
    elif missing:
        outcome = "evidence_required"
    elif candidate.get("earned"):
        # An earned placement is not a new controlled property. Its decisive
        # safety proof is genuine editorial independence, already required
        # above, rather than the installation's owned-asset capacity quota.
        outcome = "build"
        safety = {
            "outcome": "build",
            "score": 100,
            "standalone_volume_limit_90d": 0,
            "reasons": [
                "All five proofs passed.",
                "Independent editorial control is verified.",
            ],
            "required_actions": [
                "Prepare the contribution or outreach for item approval.",
                "Do not buy links or condition coverage on favorable wording.",
            ],
            "scope": "earned_placement_not_owned_asset",
        }
    else:
        candidate_policy = {
            **policy,
            "minimum_content_runway_items": required_items,
            "new_asset_maintenance_units": float(
                candidate.get(
                    "maintenance_units",
                    policy.get("new_asset_maintenance_units", 1),
                )
            ),
        }
        safety_decision = evaluate_asset_candidate(
            {
                "distinct_purpose_score": int(
                    evidence.get("distinct_purpose_score", 100)
                ),
                "content_runway_items": len(runway),
                "maintenance_owner": evidence.get("maintenance_owner"),
                "authority_path": evidence.get("authority_path"),
                "measurement_plan": evidence.get("measurement_plan"),
                "distinct_audience": evidence.get("distinct_audience"),
                "risk_signals": list(risk_signals),
            },
            existing_assets,
            creation_history,
            candidate_policy,
        )
        outcome = safety_decision.outcome
        safety = {
            "outcome": safety_decision.outcome,
            "score": safety_decision.score,
            "standalone_volume_limit_90d": safety_decision.volume_limit,
            "reasons": safety_decision.reasons,
            "required_actions": safety_decision.required_actions,
        }
    return {
        "version": 5,
        "outcome": outcome,
        "all_mandatory_proofs_pass": not failed and not missing,
        "proofs": proofs,
        "missing_proofs": missing,
        "failed_proofs": failed,
        "capacity_and_portfolio_gate": safety,
        "rule": (
            "A search-result gap is only a trigger to investigate. No asset may "
            "be built until all five proofs pass and the portfolio safety gate "
            "also permits build."
        ),
    }


def _candidate(
    archetype_id: str,
    archetype: dict,
    query: str,
    gap: int,
    proof_evidence: dict | None,
) -> dict:
    return {
        "id": f"asset_candidate_{archetype_id}",
        "archetype": archetype_id,
        "label": archetype["label"],
        "asset_kind": archetype["legacy_kind"],
        "asset_type": archetype["asset_type"],
        "delivery_mode": archetype["delivery_mode"],
        "query": query,
        "measured_gap": gap,
        "surface": archetype["surfaces"],
        "purpose_hypothesis": archetype["purpose"],
        "reader_value_hypothesis": archetype["reader_value"],
        "minimum_original_items": archetype["minimum_original_items"],
        "maintenance_units": archetype["maintenance_units"],
        "impact": archetype["impact"],
        "authority": archetype["authority"],
        "speed": archetype["speed"],
        "proof_evidence": deepcopy(proof_evidence or {}),
        "risk_signals": list(
            (proof_evidence or {}).get("risk_signals", [])
        ),
        "standalone": bool(archetype.get("standalone")),
        "earned": bool(archetype.get("earned")),
    }


def build_creative_asset_portfolio(
    assets: list[dict],
    control_maps: list[dict],
    content_inventory: list[dict],
    creation_history: list[dict],
    policy: dict,
    *,
    evidence_by_archetype: dict | None = None,
) -> dict:
    """Generate useful asset concepts only in response to a measured gap."""
    weakest = min(
        control_maps,
        key=lambda item: (
            item.get("desired_count", 0),
            item.get("controlled_count", 0),
        ),
        default=None,
    )
    target = int(policy.get("desired_results_target", 7))
    if not weakest:
        return {
            "version": 5,
            "measured_gap": None,
            "candidates": [],
            "reason": "No measured query surface is available.",
        }
    gap = max(0, target - int(weakest.get("desired_count", 0)))
    if gap <= 0:
        return {
            "version": 5,
            "measured_gap": 0,
            "query": weakest.get("query"),
            "candidates": [],
            "reason": "Desired-result target is already met.",
        }
    existing_types = {
        asset.get("type") for asset in assets
        if asset.get("status") != "quarantined"
    }
    candidates = []
    supplied = evidence_by_archetype or {}
    fingerprints = Counter(
        item.get("fingerprint")
        for item in content_inventory
        if item.get("fingerprint")
    )
    portfolio_risk_signals = []
    if any(count > 1 for count in fingerprints.values()):
        portfolio_risk_signals.append("cloned_content")
    if any(
        item.get("duplicate_intent") is True
        for item in content_inventory
    ):
        portfolio_risk_signals.append("duplicate_intent")
    for archetype_id, archetype in ASSET_ARCHETYPES.items():
        if archetype["existing_types"] & existing_types:
            continue
        proof_evidence = deepcopy(supplied.get(archetype_id) or {})
        proof_evidence["risk_signals"] = sorted(set(
            proof_evidence.get("risk_signals", [])
            + portfolio_risk_signals
        ))
        candidate = _candidate(
            archetype_id,
            archetype,
            weakest.get("query"),
            gap,
            proof_evidence,
        )
        candidate["gate"] = evaluate_creative_asset_candidate(
            candidate,
            assets,
            creation_history,
            policy,
        )
        gate_order = {
            "build": 0,
            "incubate": 1,
            "evidence_required": 2,
            "reject": 3,
        }
        candidate["creative_priority_score"] = round(
            (
                archetype["impact"] * 0.45
                + archetype["speed"] * 0.25
                + min(gap, 10) * 0.3
            ) * 10,
            2,
        )
        candidate["_sort"] = (
            gate_order.get(candidate["gate"]["outcome"], 9),
            -candidate["creative_priority_score"],
        )
        candidates.append(candidate)
    candidates.sort(key=lambda item: item.pop("_sort"))
    return {
        "version": 5,
        "query": weakest.get("query"),
        "measured_gap": gap,
        "candidate_count": len(candidates),
        "outcome_counts": dict(Counter(
            item["gate"]["outcome"] for item in candidates
        )),
        "mandatory_proofs": list(MANDATORY_PROOFS),
        "candidates": candidates,
        "rule": (
            "Prefer an authoritative existing platform or an incubated section. "
            "A standalone site is exceptional and needs an independent systemic "
            "purpose that remains valuable without reputation benefit."
        ),
    }


def candidate_to_action(candidate: dict) -> dict:
    """Convert a P5 candidate into a P4 proposal/preparation action."""
    gate = candidate["gate"]
    if gate["outcome"] == "evidence_required":
        actions = [
            "Prepare and verify the separate purpose and distinct audience",
            "Document the original reader-value inventory",
            "Name a 12-month maintenance owner, cadence and capacity",
            "Document the authority, discovery and measurement path",
            "Complete cross-asset duplication, similarity and doorway review",
        ]
    elif gate["outcome"] == "incubate":
        actions = [
            "Test the concept as a distinct section or series on an existing asset",
            "Measure user demand, indexation, maintenance load and query fit",
            "Return to the five-proof gate before any standalone build",
        ]
    elif gate["outcome"] == "build":
        actions = [
            "Prepare a complete product brief and maintenance plan",
            "Prepare the exact information architecture and original launch inventory",
            "Submit the asset build as a separate owner-approved item",
        ]
    else:
        actions = [
            "Do not build this candidate",
            "Repair the failed proof or strengthen an existing asset instead",
        ]
    return {
        "priority": "P1" if candidate["impact"] >= 9 else "P2",
        "kind": "create_or_earn_new_asset",
        "source_kind": "p5_creative_asset_engine",
        "action_type": "propose_new_asset",
        "asset_kind": candidate["asset_kind"],
        "asset_type": candidate["asset_type"],
        "delivery_mode": candidate["delivery_mode"],
        "query": candidate["query"],
        "reason": (
            f"Measured desired-result gap is {candidate['measured_gap']}; "
            f"P5 outcome is {candidate['gate']['outcome']}."
        ),
        "surface": candidate["surface"],
        "value": candidate["reader_value_hypothesis"],
        "minimum_proof": list(MANDATORY_PROOFS),
        "impact": candidate["impact"],
        "authority": candidate["authority"],
        "speed": candidate["speed"],
        "time_cost": max(1, 11 - candidate["speed"]),
        "approval_required": "owner",
        "status": candidate["gate"]["outcome"],
        "asset_gate": {
            "outcome": candidate["gate"]["outcome"],
            "score": candidate["creative_priority_score"],
            "reasons": (
                candidate["gate"]["missing_proofs"]
                + candidate["gate"]["failed_proofs"]
            ),
            "required_actions": actions,
        },
        "p5_candidate": candidate,
        "actions": actions,
        "kill_criteria": [
            "No independently useful audience or intent",
            "No sustainable maintenance capacity",
            "No realistic authority and discovery path",
            "Duplicate, cloned, doorway or fake-independent pattern",
        ],
    }
