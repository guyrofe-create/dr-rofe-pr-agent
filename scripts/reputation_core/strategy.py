"""Load and expose the product's evidence-led reputation operating strategy."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STRATEGY_PATH = PROJECT_ROOT / "config" / "reputation_strategy.json"
FACT_REGISTRY_PATH = PROJECT_ROOT / "data" / "fact_registry.json"


@lru_cache(maxsize=1)
def load_strategy(path: str | Path | None = None) -> dict:
    target = Path(path) if path else STRATEGY_PATH
    with target.open("r", encoding="utf-8") as handle:
        strategy = json.load(handle)
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
    if facts.get("practice_status") != "not_currently_practicing":
        raise ValueError("strategy must preserve the owner non-practicing status")
    if not facts.get("homepage_change_prohibited"):
        raise ValueError("strategy must preserve the guyrofe.com homepage")
    channels = strategy["channel_policy"]
    disabled = set(channels.get("owner_managed_product_disabled", []))
    if not {"Instagram", "TikTok"}.issubset(disabled):
        raise ValueError("Instagram and TikTok must remain owner-managed")
    if "X" not in set(channels.get("disabled", [])):
        raise ValueError("X must remain disabled")


def canonical_facts() -> dict:
    return load_strategy()["canonical_facts"]


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
    return list(load_strategy()["ai_monitoring"]["prompts"])


def success_metrics() -> list[str]:
    return list(load_strategy()["success_metrics"])
