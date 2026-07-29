"""Deterministic weekly content cadence with approval-safe due-job planning."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def load_cadence(path: str | Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        cadence = json.load(handle)
    validate_cadence(cadence)
    return cadence


def validate_cadence(cadence: dict) -> None:
    if not cadence.get("approval_required_before_publication"):
        raise ValueError("Autonomous cadence must preserve explicit publication approval")
    streams = cadence.get("streams") or {}
    required_streams = {
        "canonical_depth",
        "health_news",
        "evergreen_knowledge",
        "media_archive",
    }
    if set(streams) != required_streams:
        raise ValueError(
            "Cadence must define the four distinct owned-property streams"
        )
    planned_channels: dict[str, int] = {}
    for stream_name, stream in streams.items():
        weekdays = stream.get("weekdays") or {}
        if stream.get("weekly_target") != len(weekdays):
            raise ValueError(f"{stream_name} weekly target must match scheduled weekdays")
        unknown_days = set(weekdays) - set(WEEKDAYS)
        if unknown_days:
            raise ValueError(f"Unknown weekdays in cadence: {sorted(unknown_days)}")
        for channels in weekdays.values():
            if len(channels) != len(set(channels)):
                raise ValueError("A channel cannot appear twice in one scheduled job")
            for channel in channels:
                planned_channels[channel] = planned_channels.get(channel, 0) + 1
    if planned_channels != cadence.get("weekly_channel_targets"):
        raise ValueError(
            "Scheduled channel counts do not match weekly_channel_targets: "
            f"{planned_channels}"
        )
    quality = cadence.get("quality_policy") or {}
    if not quality.get("ai_image_generation_forbidden"):
        raise ValueError("AI image generation must remain forbidden")
    if not quality.get("skip_instead_of_forcing_weak_content"):
        raise ValueError("Cadence must skip weak content instead of filling a quota")
    if int(quality.get("max_news_brief_age_hours", 0)) <= 0:
        raise ValueError("Cadence needs a positive max_news_brief_age_hours")
    if not quality.get("destination_role_must_match_content_stream"):
        raise ValueError("Every draft must be routed to its distinct property role")
    threshold = float(quality.get("near_duplicate_cross_domain_threshold", 0))
    if threshold < 0.75 or threshold > 0.95:
        raise ValueError("Cross-domain duplicate threshold must be between 0.75 and 0.95")
    archive = streams["media_archive"]
    if archive.get("weekly_target") != 0 or archive.get("weekdays"):
        raise ValueError("Media archive must remain event-driven, not quota-driven")
    if int(archive.get("minimum_days_between_publications", 0)) < 14:
        raise ValueError("Media archive needs at least 14 days between publications")


def local_now(now: datetime, cadence: dict) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Cadence planning requires a timezone-aware datetime")
    return now.astimezone(ZoneInfo(cadence["timezone"]))


def week_key(now: datetime, cadence: dict) -> str:
    localized = local_now(now, cadence)
    days_since_sunday = (localized.weekday() + 1) % 7
    sunday = localized.date() - timedelta(days=days_since_sunday)
    return f"week-of-{sunday.isoformat()}"


def due_jobs(cadence: dict, state: dict, now: datetime) -> list[dict]:
    """Return each stream due today at most once; never authorizes publication."""
    localized = local_now(now, cadence)
    weekday = WEEKDAYS[localized.weekday()]
    current_week = week_key(now, cadence)
    generated = {
        (item.get("stream"), item.get("local_date"))
        for item in state.get("generated", [])
        if item.get("week") == current_week
    }
    jobs = []
    for stream_name, stream in cadence["streams"].items():
        if weekday not in stream["weekdays"]:
            continue
        key = (stream_name, localized.date().isoformat())
        if key in generated:
            continue
        jobs.append({
            "stream": stream_name,
            "site_key": stream["site_key"],
            "channels": list(stream["weekdays"][weekday]),
            "week": current_week,
            "local_date": localized.date().isoformat(),
            "weekday": weekday,
            "public_execution_allowed": False,
        })
    return jobs


def record_generation(state: dict, job: dict, draft_path: str, created_at: str) -> dict:
    entries = [
        item
        for item in state.get("generated", [])
        if not (
            item.get("stream") == job["stream"]
            and item.get("local_date") == job["local_date"]
        )
    ]
    entries.append({
        **job,
        "draft_path": draft_path,
        "created_at": created_at,
        "public_execution_allowed": False,
    })
    ordered = sorted(
        entries,
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )
    return {"version": 1, "generated": ordered[:60]}
