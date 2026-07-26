"""Load and expose the product's evidence-led reputation operating strategy."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .installation import config_path, data_path

STRATEGY_PATH = config_path("reputation_strategy.json")
CLIENT_PROFILE_PATH = config_path("client_profile.json")
FACT_REGISTRY_PATH = data_path("fact_registry.json")


@lru_cache(maxsize=1)
def load_client_profile(path: str | Path | None = None) -> dict:
    target = Path(path) if path else CLIENT_PROFILE_PATH
    with target.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    validate_client_profile(profile)
    return profile


def validate_client_profile(profile: dict) -> None:
    required = {
        "version",
        "client_id",
        "display_name",
        "deployment_mode",
        "market",
        "search_goal",
        "canonical_facts",
        "channel_policy",
        "approval_policy",
        "asset_policy",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ValueError("client profile missing keys: " + ", ".join(missing))
    if profile["deployment_mode"] != "single_tenant":
        raise ValueError("this product build supports one client per deployment")
    queries = profile["search_goal"].get("primary_queries", [])
    if not queries or any(not item.get("query") for item in queries):
        raise ValueError("client profile needs at least one primary search query")
    facts = profile["canonical_facts"]
    if not facts.get("primary_name") or not facts.get("canonical_site"):
        raise ValueError("client profile needs a primary name and canonical site")
    if not profile["approval_policy"].get("public_publication_required"):
        raise ValueError("public publication must require client approval")


@lru_cache(maxsize=1)
def load_strategy(path: str | Path | None = None) -> dict:
    target = Path(path) if path else STRATEGY_PATH
    with target.open("r", encoding="utf-8") as handle:
        strategy = json.load(handle)
    if path is None:
        profile = load_client_profile()
        strategy["canonical_facts"] = profile["canonical_facts"]
        strategy["channel_policy"] = profile["channel_policy"]
        strategy["ai_monitoring"]["prompts"] = (
            profile.get("ai_evaluation", {}).get("monitoring_prompts", [])
        )
        strategy["objective"] = profile["search_goal"]["statement"]
    validate_strategy(strategy)
    return strategy


def validate_strategy(strategy: dict) -> None:
    required = {
        "version",
        "objective",
        "canonical_facts",
        "content_policy",
        "channel_policy",
        "evidence_policy",
        "ai_monitoring",
        "success_metrics",
        "priorities",
    }
    missing = sorted(required - strategy.keys())
    if missing:
        raise ValueError("reputation strategy missing keys: " + ", ".join(missing))
    facts = strategy["canonical_facts"]
    if not facts.get("primary_name") or not facts.get("canonical_site"):
        raise ValueError("strategy needs configured client identity facts")


def canonical_facts() -> dict:
    return load_strategy()["canonical_facts"]


def client_search_queries(include_variants: bool = True) -> list[str]:
    goal = load_client_profile()["search_goal"]
    queries = [item["query"] for item in goal["primary_queries"]]
    if include_variants:
        queries.extend(goal.get("measurement_variants", []))
    return list(dict.fromkeys(queries))


def client_asset_policy() -> dict:
    return dict(load_client_profile()["asset_policy"])


def client_content_plan() -> dict:
    return dict(load_client_profile().get("content_plan", {}))


@lru_cache(maxsize=1)
def load_fact_registry(path: str | Path | None = None) -> dict:
    target = Path(path) if path else FACT_REGISTRY_PATH
    with target.open("r", encoding="utf-8") as handle:
        registry = json.load(handle)
    facts = registry.get("facts", [])
    if not facts:
        raise ValueError("fact registry contains no approved facts")
    if any(fact.get("status") == "approved" and not fact.get("evidence") for fact in facts):
        raise ValueError("every approved fact must contain evidence")
    return registry


def content_generation_prompt() -> str:
    strategy = load_strategy()
    registry = load_fact_registry()
    facts = strategy["canonical_facts"]
    policy = strategy["content_policy"]
    approved_fields = ", ".join(
        fact["field"]
        for fact in registry["facts"]
        if fact.get("status") == "approved" and fact.get("public")
    )
    return (
        "כללי ידע מחייבים של Reputation Agent:\n"
        f"- מקור האמת הקנוני: {facts['canonical_site']}\n"
        f"- סטטוס נוכחי: {facts['public_status_he']}\n"
        f"- קריאה לפעולה מותרת בלבד: {facts['allowed_cta_he']}\n"
        "- אין להמציא ניסיון, תפקיד, תואר, נתון, ציטוט או מקור.\n"
        f"- שדות העובדות הציבוריות המאושרות בלבד: {approved_fields}.\n"
        "- יש להפריד בין עובדה מאומתת, טענה ועניין שאינו ידוע.\n"
        "- תוכן רפואי הוא מידע כללי בלבד ומחייב ביקורת אנושית לפני פרסום.\n"
        + (
            f"- מאמר רפואי יכלול לפחות {policy['minimum_authoritative_sources']} "
            "מקורות סמכותיים וקישורים ישירים.\n"
            if policy.get("sources_section_required_for_medical_articles")
            else ""
        )
    )


def ensure_product_channel_allowed(channel: str) -> None:
    policy = load_strategy()["channel_policy"]
    blocked = set(policy.get("owner_managed_product_disabled", []))
    blocked.update(policy.get("disabled", []))
    blocked.update(policy.get("deferred_until_unique_use", []))
    if channel in blocked:
        raise ValueError(f"product publishing is disabled for {channel}")


def monitoring_prompts() -> list[str]:
    profile = load_client_profile()
    prompts = profile.get("ai_evaluation", {}).get("monitoring_prompts", [])
    return list(prompts or load_strategy()["ai_monitoring"]["prompts"])


def success_metrics() -> list[str]:
    return list(load_strategy()["success_metrics"])
