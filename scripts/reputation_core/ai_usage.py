"""Durable, privacy-safe OpenAI usage accounting for weekly cost reports."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USAGE_DIR = ROOT / "data" / "ai_usage_events"
WEB_SEARCH_CALL_USD = 0.01
MODEL_PRICES_PER_MILLION = {
    "gpt-5.6": {
        "input": 5.0, "cached_input": 0.5, "cache_write": 6.25, "output": 30.0,
    },
    "gpt-5.6-sol": {
        "input": 5.0, "cached_input": 0.5, "cache_write": 6.25, "output": 30.0,
    },
    "gpt-5.6-terra": {
        "input": 2.5, "cached_input": 0.25, "cache_write": 3.125, "output": 15.0,
    },
    "gpt-5.6-luna": {
        "input": 1.0, "cached_input": 0.1, "cache_write": 1.25, "output": 6.0,
    },
}


def _field(value, name, default=0):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _output_type(item):
    return _field(item, "type", "")


def _usage_numbers(response):
    usage = _field(response, "usage", None)
    if not usage:
        return None
    input_tokens = _field(usage, "input_tokens", None)
    output_tokens = _field(usage, "output_tokens", None)
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None
    input_details = _field(usage, "input_tokens_details", {}) or {}
    output_details = _field(usage, "output_tokens_details", {}) or {}
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": int(
            _field(input_details, "cached_tokens", 0) or 0
        ),
        "cache_write_tokens": int(
            _field(input_details, "cache_write_tokens", 0) or 0
        ),
        "output_tokens": output_tokens,
        "reasoning_tokens": int(
            _field(output_details, "reasoning_tokens", 0) or 0
        ),
    }


def _web_search_calls(response):
    return sum(
        1
        for item in (_field(response, "output", []) or [])
        if _output_type(item) == "web_search_call"
    )


def estimate_cost_usd(model, usage, web_search_calls=0):
    prices = MODEL_PRICES_PER_MILLION.get(model)
    if not prices:
        return None
    cached = min(usage["cached_input_tokens"], usage["input_tokens"])
    cache_write = min(
        usage.get("cache_write_tokens", 0),
        usage["input_tokens"] - cached,
    )
    uncached = usage["input_tokens"] - cached - cache_write
    return round(
        (
            uncached * prices["input"]
            + cached * prices["cached_input"]
            + cache_write * prices["cache_write"]
            + usage["output_tokens"] * prices["output"]
        )
        / 1_000_000
        + web_search_calls * WEB_SEARCH_CALL_USD,
        8,
    )


def record_ai_usage(
    response,
    *,
    operation,
    model,
    usage_dir=None,
    occurred_at=None,
):
    """Store token totals and cost only; prompts and model output are excluded."""
    occurred_at = occurred_at or datetime.now(timezone.utc)
    usage_dir = Path(
        usage_dir
        or os.environ.get("AI_USAGE_EVENT_DIR")
        or DEFAULT_USAGE_DIR
    )
    usage = _usage_numbers(response)
    if usage is None:
        return None
    web_search_calls = _web_search_calls(response)
    event = {
        "version": 1,
        "occurred_at": occurred_at.isoformat().replace("+00:00", "Z"),
        "operation": operation,
        "model": model,
        **usage,
        "web_search_calls": web_search_calls,
        "estimated_cost_usd": estimate_cost_usd(
            model,
            usage,
            web_search_calls,
        ),
    }
    usage_dir.mkdir(parents=True, exist_ok=True)
    stamp = occurred_at.strftime("%Y%m%dT%H%M%S.%fZ")
    path = usage_dir / f"{stamp}-{uuid.uuid4().hex}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(event, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return event


def load_usage_events(start, end, usage_dir=None):
    usage_dir = Path(usage_dir or DEFAULT_USAGE_DIR)
    events = []
    if not usage_dir.exists():
        return events
    for path in usage_dir.glob("*.json"):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
            occurred_at = datetime.fromisoformat(
                event["occurred_at"].replace("Z", "+00:00")
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if start <= occurred_at < end:
            events.append(event)
    return sorted(events, key=lambda item: item["occurred_at"])
