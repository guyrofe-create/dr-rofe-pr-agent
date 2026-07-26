"""P3 visibility measurement across independent search and AI surfaces."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse


RANK_WEIGHTS = {position: 1 / position for position in range(1, 11)}
ABSENT_POSITION = 11
_WORD = re.compile(r"[\w\u0590-\u05FF]{4,}", re.UNICODE)
_STOP_WORDS = {
    "אשר", "כאשר", "דרך", "מידע", "המשתמש", "הלקוח", "מקורות",
    "that", "with", "from", "through", "customer", "sources",
}


def _host(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    return parsed.netloc.lower().removeprefix("www.")


def _iso_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def serp_dimension(sample: dict) -> dict:
    """Return dimensions that must never be blended into one measurement."""
    return {
        "engine": str(sample.get("engine") or "google").lower(),
        "surface": sample.get("surface") or "web_search",
        "interface": sample.get("interface") or "api",
        "collection_method": (
            sample.get("collection_method") or "unknown_provider"
        ),
        "query": sample.get("query") or sample.get("keyword"),
        "country": sample.get("country", "IL"),
        "language": sample.get("language", "he"),
        "device": sample.get("device", "unknown"),
    }


def _serp_key(sample: dict) -> tuple:
    dimension = serp_dimension(sample)
    return tuple(dimension.values())


def measure_serp_surface(control_map: dict, sample: dict) -> dict:
    """Measure one exact engine/surface/interface/query/device observation."""
    results = control_map.get("results", [])
    controlled = [item for item in results if item.get("controlled")]
    desired = [item for item in results if item.get("desired")]
    negative = [
        item for item in results
        if item.get("sentiment") in {"negative", "harmful"}
    ]
    feature_payload = sample.get("features") or {}
    features = {
        name: bool(value)
        for name, value in feature_payload.items()
    }
    return {
        "kind": "serp_surface_measurement",
        **serp_dimension(sample),
        "observed_at": (
            sample.get("observed_at") or control_map.get("observed_at")
        ),
        "controlled_count_top10": len(controlled),
        "desired_count_top10": len(desired),
        "controlled_positions": [item["position"] for item in controlled],
        "desired_positions": [item["position"] for item in desired],
        "negative_count_top10": len(negative),
        "negative_positions": [item["position"] for item in negative],
        "weighted_controlled_score": round(sum(
            RANK_WEIGHTS.get(item["position"], 0) for item in controlled
        ), 4),
        "weighted_desired_score": round(sum(
            RANK_WEIGHTS.get(item["position"], 0) for item in desired
        ), 4),
        "weighted_negative_exposure": round(sum(
            RANK_WEIGHTS.get(item["position"], 0) for item in negative
        ), 4),
        "features": features,
        "feature_count": sum(features.values()),
        "results": [
            {
                "position": item.get("position"),
                "url": item.get("url") or item.get("link"),
                "controlled": bool(item.get("controlled")),
                "desired": bool(item.get("desired")),
                "sentiment": item.get("sentiment", "unknown"),
            }
            for item in results
        ],
    }


def _position_map(measurement: dict) -> dict[str, int]:
    return {
        item["url"]: int(item["position"])
        for item in measurement.get("results", [])
        if item.get("url") and item.get("position")
    }


def _window_volatility(
    measurements: list[dict],
    days: int,
    as_of: datetime,
) -> dict:
    cutoff = as_of - timedelta(days=days)
    selected = sorted(
        (
            item for item in measurements
            if _iso_datetime(item.get("observed_at")) >= cutoff
        ),
        key=lambda item: _iso_datetime(item.get("observed_at")),
    )
    movements = []
    for previous, current in zip(selected, selected[1:]):
        before = _position_map(previous)
        after = _position_map(current)
        for url in before.keys() | after.keys():
            movements.append(abs(
                before.get(url, ABSENT_POSITION)
                - after.get(url, ABSENT_POSITION)
            ))
    desired_counts = [
        item.get("desired_count_top10", 0) for item in selected
    ]
    return {
        "days": days,
        "samples": len(selected),
        "comparisons": max(0, len(selected) - 1),
        "mean_absolute_position_change": (
            round(sum(movements) / len(movements), 4)
            if movements else None
        ),
        "maximum_position_change": max(movements) if movements else None,
        "desired_count_range": (
            max(desired_counts) - min(desired_counts)
            if desired_counts else None
        ),
    }


def add_serp_volatility(
    current: list[dict],
    history: list[dict],
    *,
    as_of: datetime | None = None,
) -> list[dict]:
    """Attach 7/28-day volatility without mixing measurement dimensions."""
    now = as_of or datetime.now(timezone.utc)
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for item in history + current:
        grouped[_serp_key(item)].append(item)
    output = []
    for item in current:
        peers = grouped[_serp_key(item)]
        output.append({
            **item,
            "volatility": {
                "7d": _window_volatility(peers, 7, now),
                "28d": _window_volatility(peers, 28, now),
            },
        })
    return output


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(value or "")
        if token.casefold() not in _STOP_WORDS
    }


def _narrative_coverage(answer: str, narratives: list[str]) -> float | None:
    if not narratives:
        return None
    answer_tokens = _tokens(answer)
    scores = []
    for narrative in narratives:
        expected = _tokens(narrative)
        if expected:
            scores.append(len(expected & answer_tokens) / len(expected))
    return round(sum(scores) / len(scores), 4) if scores else None


def ai_dimension(sample: dict) -> dict:
    """Keep API and consumer-product answers as independent surfaces."""
    return {
        "engine": sample.get("engine") or "unknown",
        "surface": sample.get("surface") or "unknown_ai_surface",
        "interface": sample.get("interface") or "unknown_interface",
        "collection_method": (
            sample.get("collection_method") or "unknown_collection"
        ),
        "model": sample.get("model") or "unknown_model",
        "country": sample.get("country") or "unknown",
        "language": sample.get("language") or "unknown",
        "prompt": sample.get("prompt") or "",
    }


def _ai_key(sample: dict) -> tuple:
    return tuple(ai_dimension(sample).values())


def _agreement(values: list) -> float | None:
    if len(values) < 2:
        return None
    _value, count = Counter(values).most_common(1)[0]
    return round(count / len(values), 4)


def measure_ai_surfaces(
    samples: list[dict],
    approved_hosts: set[str],
    desired_narratives: list[str] | None = None,
) -> list[dict]:
    """Measure each AI engine/surface/interface/prompt independently."""
    valid = [
        sample for sample in samples
        if sample.get("status") not in {"error", "skipped"}
        and (
            sample.get("exact_answer") is not None
            or sample.get("fact_evaluation")
        )
    ]
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for sample in valid:
        grouped[_ai_key(sample)].append(sample)
    reports = []
    for group in grouped.values():
        sample_metrics = []
        all_hosts = set()
        approved_citations = total_citations = 0
        for sample in group:
            answer = sample.get("exact_answer") or ""
            hosts = {
                _host(url) for url in sample.get("cited_sources", []) if url
            } - {""}
            all_hosts.update(hosts)
            approved = hosts & approved_hosts
            approved_citations += len(approved)
            total_citations += len(hosts)
            fact_evaluation = sample.get("fact_evaluation") or {}
            factual = (
                fact_evaluation.get("status") == "pass"
                if fact_evaluation
                else sample.get("factual_accuracy") is True
            )
            identity = sample.get("identity_correct")
            if identity is None:
                identity = bool(
                    sample.get("entity_mentioned")
                    or sample.get("mentions_dr_rofe")
                ) and not sample.get("identity_misinformation")
            harmful = bool(
                sample.get("harmful_information")
                or sample.get("identity_misinformation")
                or sample.get("active_practice_claim")
                or fact_evaluation.get("status") == "fail"
            )
            narrative = sample.get("narrative_coverage")
            if narrative is None:
                narrative = _narrative_coverage(
                    answer, desired_narratives or []
                )
            sample_metrics.append({
                "identity_correct": bool(identity),
                "factual_accuracy": bool(factual),
                "narrative_coverage": narrative,
                "approved_source_cited": bool(approved),
                "harmful_or_incorrect": harmful,
                "citation_hosts": sorted(hosts),
            })
        count = len(sample_metrics)
        narrative_scores = [
            item["narrative_coverage"] for item in sample_metrics
            if item["narrative_coverage"] is not None
        ]
        stability_inputs = [
            _agreement([
                item[field] for item in sample_metrics
            ])
            for field in (
                "identity_correct", "factual_accuracy",
                "approved_source_cited", "harmful_or_incorrect",
            )
        ]
        stability_values = [
            value for value in stability_inputs if value is not None
        ]
        reports.append({
            "kind": "ai_surface_measurement",
            **ai_dimension(group[0]),
            "samples": count,
            "identity_accuracy_rate": round(sum(
                item["identity_correct"] for item in sample_metrics
            ) / count, 4),
            "factual_accuracy_rate": round(sum(
                item["factual_accuracy"] for item in sample_metrics
            ) / count, 4),
            "desired_narrative_coverage": (
                round(sum(narrative_scores) / len(narrative_scores), 4)
                if narrative_scores else None
            ),
            "approved_source_citation_rate": round(sum(
                item["approved_source_cited"] for item in sample_metrics
            ) / count, 4),
            "approved_citation_share": (
                round(approved_citations / total_citations, 4)
                if total_citations else 0.0
            ),
            "source_diversity": {
                "unique_hosts": len(all_hosts),
                "hosts": sorted(all_hosts),
                "unique_hosts_per_sample": round(
                    len(all_hosts) / count, 4
                ),
            },
            "harmful_or_incorrect_rate": round(sum(
                item["harmful_or_incorrect"] for item in sample_metrics
            ) / count, 4),
            "cross_sample_stability": (
                round(sum(stability_values) / len(stability_values), 4)
                if stability_values else None
            ),
            "sample_metrics": sample_metrics,
        })
    return reports


def summarize_bing_ai_performance(dataset: dict) -> dict:
    """Summarize an authorized BWT UI export without calling an invented API."""
    rows = dataset.get("rows", [])
    pages = {row.get("cited_url") for row in rows if row.get("cited_url")}
    queries = {
        row.get("grounding_query")
        for row in rows if row.get("grounding_query")
    }
    citations = sum(int(row.get("citations") or 0) for row in rows)
    return {
        "kind": "bing_ai_performance_measurement",
        "engine": "Bing",
        "surface": "ai_performance",
        "interface": "bing_webmaster_tools_consumer_ui",
        "collection_method": dataset.get(
            "collection_method", "authorized_manual_export"
        ),
        "status": "ok" if rows else "no_data",
        "period": dataset.get("period"),
        "total_citations": citations,
        "unique_cited_pages": len(pages),
        "unique_grounding_queries": len(queries),
        "cited_pages": sorted(pages),
        "grounding_queries": sorted(queries),
        "note": (
            "Bing AI Performance has no documented public export API; "
            "UI-export evidence is stored separately from API measurements."
        ),
    }
