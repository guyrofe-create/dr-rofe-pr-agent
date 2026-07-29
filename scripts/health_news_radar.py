#!/usr/bin/env python3
"""Build one review-only Israeli health-news brief for drguyrofe.co.il."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from xml.etree import ElementTree

import requests

try:
    from scripts.reputation_core.editorial_radar import build_news_analysis_brief, rank_news_candidates
except ModuleNotFoundError:
    from reputation_core.editorial_radar import build_news_analysis_brief, rank_news_candidates


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "israeli_health_news_sources.json"
DEFAULT_STATE = ROOT / "data" / "health_news_radar.json"
DEFAULT_BRIEF_DIR = ROOT / "opportunity_drafts"
USER_AGENT = "DrRofeHealthNewsRadar/1.0 (+https://www.drguyrofe.co.il)"
TRACKING_PARAMETERS = {"fbclid", "gclid", "utm_campaign", "utm_content", "utm_medium", "utm_source", "utm_term"}

HEALTH_TERMS = {
    "בריאות", "רפואה", "רפואי", "מחקר", "מטופל", "מטופלת", "חולה", "מחלה",
    "טיפול", "תרופה", "חיסון", "סרטן", "לב", "מוח", "סוכרת", "תזונה", "שינה",
    "הריון", "לידה", "פוריות", "נשים", "גינקולוג", "וירוס", "חיידק", "בדיקה",
}
ANALYSIS_GAP_TERMS = {
    "מחקר חדש", "מחקר מצא", "לראשונה", "פריצת דרך", "מפתיע", "עשוי", "עלול",
    "סיכון", "קשר בין", "יעיל", "מונע", "גורם ל", "אחוז",
}
SENSATIONAL_TERMS = {
    "נס", "מהפכני", "מדהים", "לא תאמינו", "חובה", "סוד", "מסוכן מאוד", "קטלני",
}


def _text(element: ElementTree.Element, names: tuple[str, ...]) -> str:
    for child in element.iter():
        if child.tag.rsplit("}", 1)[-1].lower() in names and child.text:
            return child.text.strip()
    return ""


def _clean_text(value: str, limit: int = 400) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html.unescape(value or ""))
    return re.sub(r"\s+", " ", without_tags).strip()[:limit]


def _normalize_url(value: str) -> str:
    parsed = urlparse((value or "").strip())
    query = urlencode([(key, val) for key, val in parse_qsl(parsed.query) if key.lower() not in TRACKING_PARAMETERS])
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", query, ""))


def _published_at(raw_value: str, now: datetime) -> str:
    if not raw_value:
        return now.isoformat()
    try:
        parsed = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return now.isoformat()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def parse_feed(xml_text: str, source: dict, now: datetime) -> list[dict]:
    root = ElementTree.fromstring(xml_text)
    entries = [
        element for element in root.iter()
        if element.tag.rsplit("}", 1)[-1].lower() in {"item", "entry"}
    ]
    results = []
    allowed_hosts = set(source["allowed_hosts"])
    for entry in entries:
        title = _clean_text(_text(entry, ("title",)), 220)
        link = _text(entry, ("link",))
        if not link:
            for child in entry.iter():
                if child.tag.rsplit("}", 1)[-1].lower() == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
        link = _normalize_url(link)
        if not title or urlparse(link).hostname not in allowed_hosts:
            continue
        description = _clean_text(_text(entry, ("description", "summary", "content")), 400)
        published = _text(entry, ("pubdate", "published", "updated", "date"))
        results.append({
            "title": title,
            "url": link,
            "summary": description,
            "feed_position": len(results) + 1,
            "published_at": _published_at(published, now),
            "source_id": source["id"],
            "source_name": source["name"],
            "source_kind": "major_news",
        })
    return results


def _term_score(text: str, terms: set[str], divisor: int = 1) -> int:
    matches = sum(1 for term in terms if term in text)
    return max(0, min(5, (matches + divisor - 1) // divisor))


def enrich_candidate(
    candidate: dict,
    blocked_markers: list[str],
    recent_sources: set[str],
    diversity_penalty: int = 5,
) -> dict:
    searchable = f"{candidate['title']} {candidate.get('summary', '')}".lower()
    prohibited = any(marker.lower() in searchable for marker in blocked_markers)
    relevance = _term_score(searchable, HEALTH_TERMS, divisor=2)
    analysis_gap = _term_score(searchable, ANALYSIS_GAP_TERMS)
    sensationalism = _term_score(searchable, SENSATIONAL_TERMS)
    feed_position = int(candidate.get("feed_position", 99))
    prominence = 2 if feed_position <= 5 else 1 if feed_position <= 10 else 0
    attention = min(5, 1 + prominence + analysis_gap + (1 if re.search(r"\d", searchable) else 0))
    return {
        **candidate,
        "attention_score": attention,
        "attention_signal_basis": "rss_feed_prominence_title_and_recency_proxy",
        "public_health_relevance": relevance,
        "analysis_gap": analysis_gap,
        "sensationalism_risk": sensationalism,
        "source_diversity_penalty": diversity_penalty if candidate["source_id"] in recent_sources else 0,
        "prohibited": prohibited,
    }


def recent_selected_sources(state: dict, now: datetime, cooldown_days: int) -> set[str]:
    cutoff = now - timedelta(days=cooldown_days)
    selected = state.get("selection_history", [])
    return {
        item.get("source_id")
        for item in selected
        if item.get("source_id")
        and datetime.fromisoformat(item["selected_at"].replace("Z", "+00:00")) >= cutoff
    }


def fetch_source(source: dict, timeout: int = 20) -> str:
    response = requests.get(
        source["feed_url"],
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/xml"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def run(
    config_path: Path = DEFAULT_CONFIG,
    state_path: Path = DEFAULT_STATE,
    brief_dir: Path = DEFAULT_BRIEF_DIR,
    now: datetime | None = None,
    fetcher=fetch_source,
) -> dict:
    now = now or datetime.now(timezone.utc)
    config = _load_json(config_path, {})
    previous = _load_json(state_path, {"selection_history": []})
    selection_config = config["selection"]
    recent_sources = recent_selected_sources(previous, now, selection_config["source_cooldown_days"])
    candidates: list[dict] = []
    source_results = []

    for source in config["sources"]:
        if not source.get("enabled", False):
            continue
        try:
            parsed = parse_feed(fetcher(source), source, now)
            parsed = parsed[:selection_config["candidate_limit_per_source"]]
            candidates.extend(
                enrich_candidate(
                    item,
                    config["blocked_markers"],
                    recent_sources,
                    selection_config["source_diversity_penalty"],
                )
                for item in parsed
            )
            source_results.append({"source_id": source["id"], "status": "ok", "candidate_count": len(parsed)})
        except (requests.RequestException, ElementTree.ParseError, KeyError, ValueError) as exc:
            source_results.append({"source_id": source["id"], "status": "error", "error": str(exc)[:300]})

    max_age = selection_config["max_age_hours"]
    previously_selected_urls = {
        item.get("url") for item in previous.get("selection_history", []) if item.get("url")
    }
    candidates = [
        item for item in candidates
        if (now - datetime.fromisoformat(item["published_at"])).total_seconds() / 3600 <= max_age
        and item["url"] not in previously_selected_urls
    ]
    ranked = rank_news_candidates(candidates, limit=10, now=now)
    ranked = [
        item for item in ranked
        if item["opportunity_score"] >= selection_config["minimum_opportunity_score"]
    ]
    selected = ranked[0] if ranked else None
    history = previous.get("selection_history", [])[-29:]
    brief_path = None

    if selected:
        selection_id = hashlib.sha256(selected["url"].encode("utf-8")).hexdigest()[:16]
        brief_path = brief_dir / f"health-news-{selection_id}.json"
        if not brief_path.exists():
            brief = build_news_analysis_brief(
                selected,
                destination_site_key=config["destination_site_key"],
                destination_url=config["destination_url"],
                now=now,
            )
            brief.update({
                "id": selection_id,
                "created_at": now.isoformat(),
                "source_metadata_only": True,
                "article_body_copied": False,
            })
            brief_dir.mkdir(parents=True, exist_ok=True)
            brief_path.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if not any(item.get("selection_id") == selection_id for item in history):
            history.append({
                "selection_id": selection_id,
                "source_id": selected["source_id"],
                "url": selected["url"],
                "selected_at": now.isoformat(),
            })

    state = {
        "version": 1,
        "run_at": now.isoformat(),
        "destination_site_key": config["destination_site_key"],
        "destination_url": config["destination_url"],
        "public_execution_allowed": False,
        "source_results": source_results,
        "ranked_candidates": ranked,
        "selected": selected,
        "brief_path": str(brief_path.relative_to(ROOT)) if brief_path and brief_path.is_relative_to(ROOT) else str(brief_path) if brief_path else None,
        "selection_history": history,
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state-path", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--brief-dir", type=Path, default=DEFAULT_BRIEF_DIR)
    args = parser.parse_args()
    state = run(args.config, args.state_path, args.brief_dir)
    print(json.dumps({
        "status": "brief_ready" if state["selected"] else "no_eligible_candidate",
        "selected": state["selected"]["title"] if state["selected"] else None,
        "brief_path": state["brief_path"],
        "public_execution_allowed": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
