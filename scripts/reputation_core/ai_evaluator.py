"""Fail-closed evaluation of AI answers against the approved fact registry."""
from __future__ import annotations

import re


def _normalize(value) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    return " ".join(str(value or "").lower().split())


def _approved_by_field(registry: dict) -> dict[str, dict]:
    return {
        fact["field"]: fact
        for fact in registry.get("facts", [])
        if fact.get("status") == "approved" and fact.get("public")
    }


def _unknown_fields(registry: dict) -> set[str]:
    return {
        item["field"]
        for item in registry.get("unknowns", [])
        if item.get("status") in {"evidence_required", "unknown", "disputed"}
    }


def _fact_supported(field: str, fact: dict, answer: str) -> bool:
    normalized = _normalize(answer)
    value = _normalize(fact.get("display_value") or fact.get("value"))
    if field == "primary_name":
        values = fact.get("value")
        candidates = values if isinstance(values, list) else [values]
        return any(_normalize(candidate) in normalized for candidate in candidates if candidate)
    if field == "canonical_site":
        canonical = value.removeprefix("https://").removeprefix("http://")
        return canonical.removeprefix("www.") in normalized.replace("www.", "")
    if field == "current_role":
        terms = [
            term for term in re.split(r"[\s,]+", value)
            if len(term) >= 4 and term not in {"ומחבר"}
        ]
        return sum(term in normalized for term in terms) >= min(2, len(terms))
    if field == "podcast":
        return value in normalized
    if field == "practice_status":
        terms = [term for term in re.split(r"[\s,.;:]+", value) if len(term) >= 4]
        return bool(terms) and sum(term in normalized for term in terms) >= min(2, len(terms))
    return bool(value and value in normalized)


def evaluate_ai_answer(
    prompt: str,
    answer: str,
    registry: dict,
    evaluation_policy: dict,
    *,
    known_conflict: bool = False,
    active_practice_claim: bool = False,
    knowledge_gap: bool = False,
) -> dict:
    """Evaluate only what can be proven; ambiguity is review, never pass."""
    normalized_prompt = _normalize(prompt)
    approved = _approved_by_field(registry)
    unknown = _unknown_fields(registry)
    matching_rules = [
        rule for rule in evaluation_policy.get("prompt_rules", [])
        if any(
            _normalize(marker) in normalized_prompt
            for marker in rule.get("prompt_contains_any", [])
        )
    ]
    required_fields = {
        field
        for rule in matching_rules
        for field in rule.get("required_fact_fields", [])
    }
    unknown_relevant = {
        field
        for rule in matching_rules
        for field in rule.get("unknown_fact_fields", [])
        if field in unknown
    }
    supported = []
    missing = []
    unregistered = []
    for field in sorted(required_fields):
        fact = approved.get(field)
        if not fact:
            unregistered.append(field)
        elif _fact_supported(field, fact, answer):
            supported.append(field)
        else:
            missing.append(field)

    required_markers_missing = []
    normalized_answer = _normalize(answer)
    for rule in matching_rules:
        markers = rule.get("required_answer_contains_any", [])
        if markers and not any(_normalize(marker) in normalized_answer for marker in markers):
            required_markers_missing.append(rule["id"])

    reasons = []
    if known_conflict:
        reasons.append("known conflicting identity or claim")
    if active_practice_claim:
        reasons.append("conflicting current-practice claim")
    if knowledge_gap:
        reasons.append("answer reports a material knowledge gap")
    if missing:
        reasons.append("required facts not supported: " + ", ".join(missing))
    if unregistered:
        reasons.append("required facts are not approved: " + ", ".join(unregistered))
    if required_markers_missing:
        reasons.append(
            "required status statement missing: "
            + ", ".join(required_markers_missing)
        )
    if unknown_relevant:
        reasons.append(
            "prompt touches evidence-gated facts: "
            + ", ".join(sorted(unknown_relevant))
        )
    if not matching_rules:
        reasons.append("no approved evaluation rule for this prompt")

    hard_fail = known_conflict or active_practice_claim
    status = "fail" if hard_fail else "review" if reasons else "pass"
    return {
        "status": status,
        "supported_fact_fields": supported,
        "missing_fact_fields": missing,
        "unregistered_fact_fields": unregistered,
        "unknown_relevant_fields": sorted(unknown_relevant),
        "reasons": reasons,
    }
