#!/usr/bin/env python3
"""Generate cadence-due drafts and a manifest for approval-bundle preparation."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.daily_run import (
        content_is_frozen,
        generate_article,
        save_draft,
        selected_topic,
    )
    from scripts.reputation_core.content_cadence import (
        due_jobs,
        load_cadence,
        record_generation,
    )
except ModuleNotFoundError:
    from daily_run import (
        content_is_frozen,
        generate_article,
        save_draft,
        selected_topic,
    )
    from reputation_core.content_cadence import (
        due_jobs,
        load_cadence,
        record_generation,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CADENCE = ROOT / "config" / "content_cadence.json"
DEFAULT_STATE = ROOT / "data" / "content_cadence_state.json"
DEFAULT_NEWS_BRIEFS = ROOT / "opportunity_drafts"
DEFAULT_MEDIA_BRIEFS = ROOT / "opportunity_drafts" / "media"
DEFAULT_APPROVAL_INDEX = ROOT / "approval_bundles" / "index.json"


def _load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def unused_news_brief(
    brief_dir: Path,
    state: dict,
    *,
    now: datetime | None = None,
    max_age_hours: int = 36,
) -> tuple[Path, dict] | None:
    now = now or datetime.now(timezone.utc)
    used = {
        item.get("source_brief")
        for item in state.get("generated", [])
        if item.get("source_brief")
    }
    candidates = []
    for path in brief_dir.glob("health-news-*.json"):
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        relative = (
            path.resolve().relative_to(ROOT).as_posix()
            if path.resolve().is_relative_to(ROOT)
            else str(path.resolve())
        )
        if relative in used:
            continue
        if (
            brief.get("status") != "draft_brief_requires_editorial_review"
            or brief.get("destination_site_key") != "DRGUYROFE_CO_IL"
            or not brief.get("analyzed_news_url")
        ):
            continue
        try:
            created_at = datetime.fromisoformat(
                str(brief.get("created_at") or "").replace("Z", "+00:00")
            )
        except ValueError:
            continue
        age_hours = (now - created_at).total_seconds() / 3600
        if age_hours < -2 or age_hours > max_age_hours:
            continue
        candidates.append((brief.get("created_at", ""), path, brief, relative))
    if not candidates:
        return None
    _created_at, path, brief, relative = max(candidates, key=lambda item: item[0])
    return path, {**brief, "_relative_path": relative}


def unused_media_brief(
    brief_dir: Path,
    state: dict,
) -> tuple[Path, dict] | None:
    used = {
        item.get("source_brief")
        for item in state.get("generated", [])
        if item.get("source_brief")
    }
    candidates = []
    for path in brief_dir.glob("media-transcript-*.json"):
        try:
            brief = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        relative = (
            path.resolve().relative_to(ROOT).as_posix()
            if path.resolve().is_relative_to(ROOT)
            else str(path.resolve())
        )
        if relative in used:
            continue
        platform_urls = brief.get("platform_urls") or {}
        podcast_links_valid = (
            brief.get("source_media_type") != "podcast"
            or (
                str(platform_urls.get("spotify") or "").startswith(
                    "https://open.spotify.com/"
                )
                and str(platform_urls.get("apple_podcasts") or "").startswith(
                    "https://podcasts.apple.com/"
                )
            )
        )
        if (
            brief.get("status") != "transcript_ready_for_editorial_review"
            or brief.get("destination_site_key") != "GUYROFE_WIX_MEDIA_ARCHIVE"
            or not str(brief.get("source_media_url") or "").startswith(
                ("https://", "http://")
            )
            or not str(brief.get("transcript_markdown") or "").strip()
            or not podcast_links_valid
        ):
            continue
        candidates.append((brief.get("created_at", ""), path, brief, relative))
    if not candidates:
        return None
    _created_at, path, brief, relative = max(candidates, key=lambda item: item[0])
    return path, {**brief, "_relative_path": relative}


def media_archive_job(cadence: dict, state: dict, now: datetime) -> dict | None:
    stream = cadence["streams"]["media_archive"]
    minimum_days = int(stream["minimum_days_between_publications"])
    generated = [
        item for item in state.get("generated", [])
        if item.get("stream") == "media_archive"
    ]
    if generated:
        latest = max(str(item.get("created_at") or "") for item in generated)
        try:
            latest_at = datetime.fromisoformat(latest.replace("Z", "+00:00"))
        except ValueError:
            latest_at = now
        if (now - latest_at).total_seconds() < minimum_days * 86400:
            return None
    return {
        "stream": "media_archive",
        "site_key": stream["site_key"],
        "channels": [],
        "week": f"event-{now.date().isoformat()}",
        "local_date": now.date().isoformat(),
        "weekday": "event_driven",
        "public_execution_allowed": False,
    }


def unbundled_generated_jobs(state: dict, approval_index_path: Path) -> list[dict]:
    """Recover generated drafts whose licensed-photo bundle previously failed."""
    approval_index = _load_json(approval_index_path, {"bundles": []})
    bundled = {
        item.get("draft_path")
        for item in approval_index.get("bundles", [])
        if item.get("draft_path")
    }
    recoveries = []
    for item in state.get("generated", []):
        draft_path = item.get("draft_path")
        if not draft_path or draft_path in bundled:
            continue
        path = Path(draft_path)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            continue
        recoveries.append({
            **item,
            "destination_site_key": item["site_key"],
            "scheduled_channels": item.get("channels", []),
            "draft_path": draft_path,
            "status": "existing_draft_ready_for_bundle_retry",
            "public_execution_allowed": False,
        })
    return recoveries


def generate_job(
    job: dict,
    now: datetime,
    news_brief_dir: Path,
    state: dict | None = None,
    max_news_brief_age_hours: int = 36,
    media_brief_dir: Path = DEFAULT_MEDIA_BRIEFS,
) -> dict | None:
    metadata = {
        "content_stream": job["stream"],
        "destination_site_key": job["site_key"],
        "scheduled_channels": job["channels"],
        "cadence_week": job["week"],
        "cadence_local_date": job["local_date"],
        "public_execution_allowed": False,
    }
    if job["stream"] == "canonical_depth":
        topic_index, topic = selected_topic(now)
        title, content = generate_article(topic)
    elif job["stream"] == "health_news":
        selected = unused_news_brief(
            news_brief_dir,
            state or {"generated": []},
            now=now,
            max_age_hours=max_news_brief_age_hours,
        )
        if not selected:
            return None
        _brief_path, brief = selected
        news_url = brief["analyzed_news_url"]
        topic_index = 90
        topic = brief["working_title"]
        context = (
            "\nכללים מיוחדים לניתוח חדשות רפואיות:\n"
            f"- יעד הפרסום הראשי של הטיוטה: {brief['destination_url']}\n"
            f"- כתבת החדשות הנבדקת: {news_url}\n"
            "- קשר לכתבת החדשות בגוף המאמר בטקסט עוגן תיאורי וברור.\n"
            "- אין להעתיק את הכתבה או להסתמך עליה כמקור רפואי.\n"
            "- השתמש בחיפוש רשת כדי לאתר את המחקר או המסמך הראשוני שעליו "
            "נשענת הכותרת, ובדוק אותו מול לפחות שני מקורות רפואיים מוסדיים "
            "ישירים נוספים.\n"
            "- הסבר מה נטען, מה הנתונים באמת מראים, מה המגבלות ומה המשמעות "
            "המעשית; הפרד קשר מסיבתיות והימנע מכותרת סנסציונית.\n"
        )
        title, content = generate_article(
            topic,
            editorial_context=context,
            allowed_external_urls={news_url},
            required_urls={news_url},
            use_web_search=True,
        )
        metadata["source_brief"] = brief["_relative_path"]
        metadata["analyzed_news_url"] = news_url
    elif job["stream"] == "evergreen_knowledge":
        topic_index, topic = selected_topic(now)
        context = (
            "\nכללים מיוחדים למרכז הידע drguyrofe.com:\n"
            "- כתוב מדריך רפואי ירוק-עד ומעמיק, לא תגובה לחדשות.\n"
            "- ענה על כוונת חיפוש רפואית אחת באופן מלא וברור.\n"
            "- אל תשכתב ואל תסכם מאמר מאתר אחר שבבעלות הלקוח.\n"
            "- קשר לאתר הרשמי רק כאשר הקישור מוסיף הקשר אמיתי לקורא.\n"
        )
        title, content = generate_article(topic, editorial_context=context)
    elif job["stream"] == "media_archive":
        selected = unused_media_brief(media_brief_dir, state or {"generated": []})
        if not selected:
            return None
        _brief_path, brief = selected
        topic_index = 95
        topic = brief["working_title"]
        title = brief["working_title"]
        content = str(brief["transcript_markdown"]).strip()
        if not content.startswith("# "):
            content = f"# {title}\n\n{content}"
        platform_urls = brief.get("platform_urls") or {}
        original_links = []
        if platform_urls.get("spotify"):
            original_links.append(
                f"- [האזנה ב‑Spotify]({platform_urls['spotify']})"
            )
        if platform_urls.get("apple_podcasts"):
            original_links.append(
                f"- [האזנה ב‑Apple Podcasts]({platform_urls['apple_podcasts']})"
            )
        if original_links:
            content = (
                f"{content.rstrip()}\n\n## האזנה לפרק המקורי\n\n"
                + "\n".join(original_links)
            )
        metadata["source_brief"] = brief["_relative_path"]
        metadata["source_media_url"] = brief["source_media_url"]
        metadata["source_media_type"] = brief.get("source_media_type", "media")
        metadata["source_media_urls"] = platform_urls
    else:
        raise ValueError(f"Unknown content stream: {job['stream']}")

    path = save_draft(
        topic_index,
        topic,
        title,
        content,
        now=now,
        metadata=metadata,
    )
    return {
        **job,
        **metadata,
        "draft_path": path.as_posix(),
        "title": title,
        "status": "draft_ready_for_bundle",
    }


def run(
    *,
    cadence_path: Path = DEFAULT_CADENCE,
    state_path: Path = DEFAULT_STATE,
    news_brief_dir: Path = DEFAULT_NEWS_BRIEFS,
    media_brief_dir: Path = DEFAULT_MEDIA_BRIEFS,
    manifest_path: Path,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    cadence = load_cadence(cadence_path)
    state = _load_json(state_path, {"version": 1, "generated": []})
    manifest = {
        "version": 1,
        "run_at": now.isoformat(),
        "approval_required_before_publication": True,
        "jobs": [],
        "skipped": [],
        "errors": [],
    }
    if content_is_frozen():
        manifest["skipped"].append({
            "stream": "all",
            "reason": "command_center_content_freeze",
            "public_execution_allowed": False,
        })
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return manifest
    manifest["jobs"].extend(
        unbundled_generated_jobs(state, DEFAULT_APPROVAL_INDEX)
    )
    planned_jobs = due_jobs(cadence, state, now)
    event_job = media_archive_job(cadence, state, now)
    if event_job and unused_media_brief(media_brief_dir, state):
        planned_jobs.append(event_job)
    for job in planned_jobs:
        try:
            result = generate_job(
                job,
                now,
                news_brief_dir,
                state,
                cadence["quality_policy"]["max_news_brief_age_hours"],
                media_brief_dir,
            )
            if result is None:
                manifest["skipped"].append({
                    **job,
                    "reason": "no_unused_eligible_health_news_brief",
                })
                continue
            manifest["jobs"].append(result)
            state = record_generation(
                state,
                {**job, "source_brief": result.get("source_brief")},
                result["draft_path"],
                now.isoformat(),
            )
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            manifest["errors"].append({
                **job,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cadence", type=Path, default=DEFAULT_CADENCE)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--news-brief-dir", type=Path, default=DEFAULT_NEWS_BRIEFS)
    parser.add_argument("--media-brief-dir", type=Path, default=DEFAULT_MEDIA_BRIEFS)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    manifest = run(
        cadence_path=args.cadence,
        state_path=args.state,
        news_brief_dir=args.news_brief_dir,
        media_brief_dir=args.media_brief_dir,
        manifest_path=args.manifest,
    )
    print(json.dumps({
        "drafts_ready": len(manifest["jobs"]),
        "skipped": len(manifest["skipped"]),
        "errors": len(manifest["errors"]),
        "public_execution_allowed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
