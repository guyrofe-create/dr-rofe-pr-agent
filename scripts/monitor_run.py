#!/usr/bin/env python3
"""
Single-tenant Reputation & Visibility Monitor
Runs every 2 hours on GitHub Actions (see .github/workflows/monitor.yml).

Checks, every run:
  1. Google rank         - configured queries vs controlled properties
  2. AI/GEO presence     - factual and citation checks for the configured client
  3. Token/session health - every configured publisher credential, still valid?
  4. Google Business reviews - rating, review count, and each individual recent
                               review (Google Places API)
  5. Facebook Page recommendations (positive/negative)
  6. Web mentions        - configured identity queries

State/history is persisted to data/reputation_history.json (committed back to
the repo each run) so the monitor can detect *changes* - a new review, a
rating drop, a new web mention - not just point-in-time snapshots.

Two kinds of GitHub Issues are opened:
  - "reputation-alert" (urgent, opened immediately the moment something bad is
     detected: new low-rating review, rating drop, new negative FB
     recommendation) - GitHub emails this to the repo owner right away.
  - "monitor-report" (the full daily digest, opened once per calendar day).
"""
import os
import sys
import json
import requests
import re
from datetime import datetime, date, timedelta
from openai import OpenAI
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta, twitter, tumblr, telegram, blogger, pinterest
from reputation_core import (
    CommandCenter,
    client_search_queries,
    fetch_search_console_rows,
    load_client_profile,
    load_fact_registry,
    monitoring_prompts,
    orchestrate_reputation_cycle,
    plan_growth_campaign,
    refresh_google_access_token,
    data_path,
)
from reputation_core.strategy import load_strategy
from reputation_core.orchestrator import load_serp_targets
from reputation_core.ai_evaluator import evaluate_ai_answer

CLIENT_PROFILE = load_client_profile()
CLIENT_FACTS = CLIENT_PROFILE["canonical_facts"]
MARKET = CLIENT_PROFILE.get("market", {})
MARKET_COUNTRY = str(MARKET.get("country", "")).upper() or "US"
MARKET_LANGUAGE = str(MARKET.get("language", "")).lower() or "en"
GOOGLE_DOMAIN = "google.co.il" if MARKET_COUNTRY == "IL" else "google.com"
GOOGLE_LANGUAGE = "iw" if MARKET_LANGUAGE == "he" else MARKET_LANGUAGE
SITE_DOMAIN = urlparse(CLIENT_FACTS["canonical_site"]).netloc.removeprefix("www.")
HISTORY_PATH = str(data_path("reputation_history.json"))
COMMAND_CENTER_PATH = str(data_path("command_center.json"))
PROFILE_PATH = str(data_path("business_profile.json"))
GROWTH_OBSERVATIONS_PATH = str(data_path("growth_observations.json"))
ASSET_REGISTRY_PATH = str(data_path("asset_registry.json"))
BING_AI_PERFORMANCE_PATH = str(data_path("bing_ai_performance.json"))

KEYWORDS = client_search_queries()

GEO_PROMPTS = monitoring_prompts()

WEB_MENTION_QUERY = " OR ".join(
    f'"{query}"' for query in client_search_queries(include_variants=False)
)

REPORT = {
    "date": datetime.now().isoformat(),
    "rank": [], "geo": [], "tokens": [], "reviews": None,
    "facebook_recommendations": None, "web_mentions": None,
    "search_console": None, "bing_ai_performance": None,
    "orchestration": None,
    "alerts": [], "errors": [],
}


def env(name):
    return os.environ.get(name, "").strip() or None


def safe_error(error):
    """Return a diagnostic without leaking credentials in URLs or payloads."""
    detail = str(error)
    for name in (
        "SERPAPI_KEY", "OPENAI_API_KEY", "GOOGLE_PLACES_API_KEY",
        "FACEBOOK_PAGE_TOKEN", "PINTEREST_ACCESS_TOKEN", "MEDIUM_TOKEN",
        "MEDIUM_SID", "TELEGRAM_BOT_TOKEN", "TWITTER_API_KEY",
        "TWITTER_API_SECRET", "TWITTER_ACCESS_TOKEN",
        "TWITTER_ACCESS_SECRET", "TUMBLR_CONSUMER_KEY",
        "TUMBLR_CONSUMER_SECRET", "TUMBLR_OAUTH_TOKEN",
        "TUMBLR_OAUTH_SECRET", "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN",
        "LINKEDIN_ACCESS_TOKEN",
    ):
        secret = env(name)
        if secret:
            detail = detail.replace(secret, "[REDACTED]")
    detail = re.sub(
        r"(?i)(api_key|access_token|key|token)=([^&\s]+)",
        r"\1=[REDACTED]",
        detail,
    )
    return detail[:500]


def normalized_host(value):
    """Return a normalized hostname, or empty text for an unconfigured URL."""
    if not isinstance(value, str) or not value.strip():
        return ""
    return urlparse(value.strip()).netloc.lower().removeprefix("www.")


def collect_search_console_evidence():
    """Collect 28-day query/page evidence when shared Google OAuth is present."""
    names = (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REFRESH_TOKEN",
    )
    credentials = [env(name) for name in names]
    if not all(credentials):
        REPORT["search_console"] = {
            "status": "skipped",
            "reason": "shared Google OAuth credentials are not configured",
            "rows": [],
        }
        return []
    try:
        access_token = refresh_google_access_token(*credentials)
        properties = load_serp_targets().get("search_console_properties", [])
        rows = fetch_search_console_rows(access_token, properties)
        REPORT["search_console"] = {
            "status": "ok",
            "properties": properties,
            "row_count": len(rows),
            "rows": rows,
        }
        return rows
    except Exception as exc:
        REPORT["search_console"] = {
            "status": "error",
            "error": safe_error(exc),
            "rows": [],
        }
        return []


def has_active_practice_claim(answer):
    normalized = " ".join((answer or "").lower().split())
    uncertainty_markers = (
        "אין לי מידע", "אין לי את המידע", "לא ידוע", "לא ברור",
        "לא ניתן לקבוע", "איני יודע", "אין מידע מעודכן",
        "i do not know", "i don't know", "it is unclear",
        "no current information", "cannot confirm",
    )
    policy = CLIENT_PROFILE.get("ai_evaluation", {})
    conflict_claims = tuple(
        marker.lower() for marker in policy.get("claim_conflict_markers", [])
    )
    recommendation_claims = tuple(
        policy.get("claim_recommendation_patterns", [])
    )
    negation_patterns = tuple(policy.get("claim_negation_patterns", []))
    for sentence in re.split(r"[.!?\n]+", normalized):
        if not sentence:
            continue
        for pattern in negation_patterns:
            sentence = re.sub(pattern, "", sentence)
        if any(re.search(pattern, sentence) for pattern in recommendation_claims):
            return True
        if any(marker in sentence for marker in uncertainty_markers):
            continue
        if any(claim in sentence for claim in conflict_claims):
            return True
    return False


def has_identity_misinformation(answer):
    """Catch known conflicting identities that must never be marked as safe."""
    normalized = " ".join((answer or "").lower().split())
    conflict_markers = tuple(
        marker.lower()
        for marker in CLIENT_PROFILE.get("ai_evaluation", {}).get(
            "identity_conflict_markers", []
        )
    )
    return any(marker in normalized for marker in conflict_markers)


def has_ai_knowledge_gap(prompt, answer):
    """Identify non-answers about public identity/assets, without treating
    uncertainty about current patient availability as misinformation."""
    prompt_normalized = " ".join((prompt or "").lower().split())
    if any(marker in prompt_normalized for marker in (
        "מקבל כיום מטופלות", "קביעת תור", "accepting patients",
    )):
        return False
    answer_normalized = " ".join((answer or "").lower().split())
    gap_markers = (
        "אין לי מידע", "אין לי גישה", "איני יכול לספק", "לא יכול לספק",
        "לא ידוע לי", "מומלץ לחפש", "אני ממליץ לחפש",
        "מומלץ לבדוק", "אני ממליץ לבדוק",
        "i do not have information", "i cannot provide", "recommended to search",
    )
    return any(marker in answer_normalized for marker in gap_markers)


def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError, TypeError):
        return default


# ─── History (state) helpers ─────────────────────────────────────────────────

def load_history():
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"snapshots": [], "seen_review_ids": [], "seen_urls": [], "last_full_digest_date": None}


def save_history(history):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    # cap history to the most recent 200 snapshots so the file doesn't grow forever
    history["snapshots"] = history.get("snapshots", [])[-200:]
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


HISTORY = load_history()


# ─── 1. Google rank via SerpApi ──────────────────────────────────────────────

def serp_checks_due(today=None):
    """Search-rank checks are daily; crisis checks still run every two hours."""
    today = today or date.today().isoformat()
    if serp_backoff_active(today):
        return False
    if HISTORY.get("last_serp_check_date") == today:
        return False
    for snapshot in reversed(HISTORY.get("snapshots", [])):
        snapshot_date = str(snapshot.get("date", ""))[:10]
        if snapshot_date != today:
            break
        statuses = {
            result.get("status") for result in snapshot.get("rank", [])
        }
        if statuses and statuses.issubset({"found", "not_in_top10"}):
            return False
    return True


def serp_backoff_active(today=None):
    """Avoid retry storms after SerpApi reports an exhausted/rate-limited quota."""
    today = today or date.today().isoformat()
    retry_on = str(HISTORY.get("serp_retry_on_date") or "")
    return bool(retry_on and today < retry_on)


def activate_serp_backoff(today=None):
    today_value = date.fromisoformat(today or date.today().isoformat())
    HISTORY["serp_retry_on_date"] = (today_value + timedelta(days=1)).isoformat()


def is_serp_quota_error(error):
    response = getattr(error, "response", None)
    return getattr(response, "status_code", None) == 429


def ai_checks_due(today=None):
    """AI-answer sampling is daily and uses repeated samples for stability."""
    today = today or date.today().isoformat()
    return HISTORY.get("last_ai_check_date") != today


def rank_measurement_succeeded() -> bool:
    """A partial/error rank run must remain retryable and visibly degraded."""
    measured = [
        item for item in REPORT.get("rank", [])
        if item.get("status") != "skipped"
    ]
    return bool(measured) and all(
        item.get("status") in {"found", "not_in_top10"} for item in measured
    )


def ai_measurement_succeeded() -> bool:
    measured = [
        item for item in REPORT.get("geo", [])
        if item.get("status") != "skipped"
    ]
    return bool(measured) and all(item.get("status") != "error" for item in measured)


def check_google_rank():
    api_key = env("SERPAPI_KEY")
    if not api_key:
        REPORT["rank"].append({"status": "skipped", "reason": "SERPAPI_KEY not set"})
        return
    queries = KEYWORDS
    devices = [
        item.strip() for item in os.environ.get("SERP_DEVICES", "mobile,desktop").split(",")
        if item.strip() in {"mobile", "desktop", "tablet"}
    ]
    engines = [
        item.strip().lower()
        for item in os.environ.get("SERP_ENGINES", "google").split(",")
        if item.strip().lower() in {"google", "bing"}
    ]
    for kw in queries:
      for engine in engines:
       for device in devices:
        try:
            params = {
                "engine": engine, "q": kw, "num": 10,
                "device": device, "api_key": api_key,
            }
            if engine == "google":
                params.update({
                    "google_domain": GOOGLE_DOMAIN,
                    "gl": MARKET_COUNTRY.lower(),
                    "hl": GOOGLE_LANGUAGE,
                })
            else:
                params["cc"] = MARKET_COUNTRY.lower()
            resp = requests.get(
                "https://serpapi.com/search.json",
                params=params,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                REPORT["rank"].append({
                    "engine": engine, "keyword": kw, "device": device,
                    "status": "error",
                    "detail": data["error"],
                })
                continue
            organic = data.get("organic_results", [])
            position = next(
                (r.get("position", i + 1) for i, r in enumerate(organic) if SITE_DOMAIN in r.get("link", "")),
                None,
            )
            REPORT["rank"].append({
                "engine": engine,
                "surface": "web_search",
                "interface": "search_data_api",
                "collection_method": "serpapi",
                "keyword": kw, "device": device, "country": MARKET_COUNTRY,
                "language": MARKET_LANGUAGE,
                "position_top10": position,
                "status": "found" if position else "not_in_top10",
                "results": [
                    {
                        "position": result.get("position", index + 1),
                        "title": result.get("title"),
                        "link": result.get("link"),
                        "displayed_link": result.get("displayed_link"),
                        "sentiment": "unknown",
                    }
                    for index, result in enumerate(organic[:10])
                ],
                "features": {
                    "knowledge_panel": bool(data.get("knowledge_graph")),
                    "images": bool(
                        data.get("inline_images")
                        or data.get("images_results")
                    ),
                    "video": bool(
                        data.get("inline_videos")
                        or data.get("video_results")
                    ),
                    "featured_snippet": bool(
                        data.get("answer_box")
                        or data.get("featured_snippet")
                    ),
                    "people_also_ask": bool(data.get("related_questions")),
                    "top_stories": bool(data.get("top_stories")),
                    "local_pack": bool(data.get("local_results")),
                },
            })
        except Exception as e:
            if is_serp_quota_error(e):
                activate_serp_backoff()
                REPORT["rank"].append({
                    "engine": engine,
                    "keyword": kw,
                    "device": device,
                    "status": "quota_limited",
                    "detail": safe_error(e),
                    "retry_on": HISTORY["serp_retry_on_date"],
                })
                return
            REPORT["rank"].append({
                "engine": engine, "keyword": kw, "device": device,
                "status": "error",
                "detail": safe_error(e),
            })


# ─── 2. AI / GEO presence check ──────────────────────────────────────────────

def check_ai_presence():
    openai_key = env("OPENAI_API_KEY")
    if not openai_key:
        REPORT["geo"].append({"status": "skipped", "reason": "OPENAI_API_KEY not set"})
        return
    client = OpenAI(api_key=openai_key)
    strategy = load_strategy()["ai_monitoring"]
    fact_registry = load_fact_registry()
    evaluation_policy = CLIENT_PROFILE.get("ai_evaluation", {})
    configured_samples = os.environ.get("AI_MONITOR_SAMPLES", "").strip()
    sample_count = int(configured_samples or strategy["samples_per_prompt"])
    sample_count = max(1, min(sample_count, 5))
    majority = sample_count // 2 + 1
    model = os.environ.get("AI_MONITOR_MODEL", "gpt-5.6-sol")
    registry = load_json_file(ASSET_REGISTRY_PATH, {"assets": []})
    approved_hosts = {
        host
        for asset in registry.get("assets", [])
        if asset.get("tier") in {"A", "B"}
        and asset.get("status") != "quarantined"
        and (host := normalized_host(asset.get("url")))
    }
    for prompt in GEO_PROMPTS:
        samples = []
        for sample_number in range(1, sample_count + 1):
            try:
                resp = client.responses.create(
                    model=model,
                    input=prompt,
                    tools=[{
                        "type": "web_search",
                        "search_context_size": "medium",
                        "user_location": {
                            "type": "approximate",
                            "country": MARKET_COUNTRY,
                        },
                    }],
                    max_output_tokens=500,
                )
                answer = resp.output_text or ""
                citations = []
                for output_item in getattr(resp, "output", []) or []:
                    for part in getattr(output_item, "content", []) or []:
                        for annotation in getattr(part, "annotations", []) or []:
                            payload = (
                                annotation.model_dump()
                                if hasattr(annotation, "model_dump")
                                else annotation if isinstance(annotation, dict) else {}
                            )
                            url = payload.get("url") or (
                                payload.get("url_citation") or {}
                            ).get("url")
                            if url and url not in citations:
                                citations.append(url)
                cited_hosts = {
                    host
                    for url in citations
                    if (host := normalized_host(url))
                }
                mentioned = any(
                    variant.lower() in answer.lower()
                    for variant in CLIENT_FACTS.get(
                        "name_variants",
                        [CLIENT_FACTS["primary_name"]],
                    )
                )
                active_practice_claim = has_active_practice_claim(answer)
                identity_misinformation = has_identity_misinformation(answer)
                knowledge_gap = (
                    not identity_misinformation
                    and has_ai_knowledge_gap(prompt, answer)
                )
                fact_evaluation = evaluate_ai_answer(
                    prompt,
                    answer,
                    fact_registry,
                    evaluation_policy,
                    known_conflict=identity_misinformation,
                    active_practice_claim=active_practice_claim,
                    knowledge_gap=knowledge_gap,
                )
                result = {
                    "engine": "OpenAI",
                    "surface": "responses_web_search",
                    "interface": "api",
                    "collection_method": "openai_responses_api",
                    "model": model,
                    "country": MARKET_COUNTRY,
                    "language": "he" if re.search(r"[\u0590-\u05FF]", prompt) else "en",
                    "sample": sample_number,
                    "prompt": prompt,
                    "mentions_dr_rofe": mentioned,
                    "active_practice_claim": active_practice_claim,
                    "identity_misinformation": identity_misinformation,
                    "knowledge_gap": knowledge_gap,
                    "official_source_cited": bool(cited_hosts & approved_hosts),
                    "cited_sources": citations,
                    "fact_evaluation": fact_evaluation,
                    "safe_status": fact_evaluation["status"],
                    "exact_answer": answer,
                    "excerpt": answer[:300],
                }
                samples.append(result)
                REPORT["geo"].append(result)
            except Exception as e:
                REPORT["geo"].append({
                    "engine": "OpenAI",
                    "model": model,
                    "sample": sample_number,
                    "prompt": prompt,
                    "status": "error",
                    "detail": safe_error(e),
                })

        alert_types = (
            ("active_practice_claim", "ai_active_practice_misinformation"),
            ("identity_misinformation", "ai_identity_misinformation"),
            ("knowledge_gap", "ai_knowledge_gap"),
        )
        for field, alert_type in alert_types:
            flagged = [sample for sample in samples if sample.get(field)]
            if len(flagged) >= majority:
                REPORT["alerts"].append({
                    "type": alert_type,
                    "source": "OpenAI repeated monitor samples",
                    "excerpt": flagged[0]["excerpt"],
                    "prompt": prompt,
                    "samples_flagged": len(flagged),
                    "samples_total": len(samples),
                    "model": model,
                })
        unsafe_samples = [
            sample for sample in samples
            if sample.get("fact_evaluation", {}).get("status") in {"fail", "review"}
        ]
        if len(unsafe_samples) >= majority and not any(
            sample.get(field)
            for sample in unsafe_samples
            for field, _ in alert_types
        ):
            REPORT["alerts"].append({
                "type": "ai_fact_review_required",
                "source": "OpenAI fact-grounded monitor",
                "excerpt": unsafe_samples[0]["excerpt"],
                "prompt": prompt,
                "samples_flagged": len(unsafe_samples),
                "samples_total": len(samples),
                "model": model,
                "reasons": unsafe_samples[0]["fact_evaluation"]["reasons"],
            })


# ─── 3. Token / session health ───────────────────────────────────────────────

def check_token_health():
    checks = [
        ("Facebook", meta.facebook_is_configured, meta.check_token_health),
        ("Twitter/X", twitter.is_configured, twitter.check_token_health),
        ("Tumblr", tumblr.is_configured, tumblr.check_token_health),
        ("Telegram", telegram.is_configured, telegram.check_token_health),
        ("Blogger", blogger.is_configured, blogger.check_token_health),
        ("Pinterest", pinterest.is_configured, pinterest.check_token_health),
    ]
    for name, configured_fn, fn in checks:
        configured = configured_fn()
        try:
            ok, detail = fn()
            REPORT["tokens"].append({
                "platform": name,
                "configured": configured,
                "ok": ok,
                "detail": safe_error(detail),
            })
        except Exception as e:
            REPORT["tokens"].append({
                "platform": name,
                "configured": configured,
                "ok": False,
                "detail": safe_error(e),
            })

    medium_sid = env("MEDIUM_SID")
    medium_token = env("MEDIUM_TOKEN")
    if medium_token:
        REPORT["tokens"].append({
            "platform": "Medium",
            "configured": True,
            "ok": True,
            "detail": "using MEDIUM_TOKEN (API)",
        })
    elif medium_sid:
        try:
            resp = requests.get(
                "https://medium.com/me/stories/drafts",
                cookies={"sid": medium_sid}, timeout=15, allow_redirects=True,
            )
            expired = "signin" in resp.url or "login" in resp.url
            REPORT["tokens"].append({
                "platform": "Medium", "configured": True, "ok": not expired,
                "detail": "session expired - refresh MEDIUM_SID" if expired else "session valid",
            })
        except Exception as e:
            REPORT["tokens"].append({
                "platform": "Medium", "configured": True, "ok": False,
                "detail": safe_error(e),
            })
    else:
        REPORT["tokens"].append({
            "platform": "Medium", "configured": False, "ok": False,
            "detail": "not configured",
        })


# ─── 4. Google Business reviews (with per-review crisis detection) ──────────

def check_reviews():
    api_key = env("GOOGLE_PLACES_API_KEY")
    place_id = env("GOOGLE_PLACE_ID")
    if not api_key or not place_id:
        REPORT["reviews"] = {"status": "skipped", "reason": "GOOGLE_PLACES_API_KEY / GOOGLE_PLACE_ID not set"}
        return
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={
                "place_id": place_id,
                "fields": "name,rating,user_ratings_total,reviews",
                "reviews_sort": "newest",
                "key": api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        reviews = result.get("reviews", []) or []

        prev_rating = None
        prev_snapshots = [s for s in HISTORY.get("snapshots", []) if s.get("reviews", {}).get("rating") is not None]
        if prev_snapshots:
            prev_rating = prev_snapshots[-1]["reviews"]["rating"]

        seen_ids = set(HISTORY.get("seen_review_ids", []))
        new_reviews = []
        for r in reviews:
            rid = f"{r.get('author_name')}|{r.get('time')}"
            if rid not in seen_ids:
                new_reviews.append(r)
                seen_ids.add(rid)

        REPORT["reviews"] = {
            "status": "ok",
            "name": result.get("name"),
            "rating": result.get("rating"),
            "total_reviews": result.get("user_ratings_total"),
            "latest_review_excerpt": (reviews[0].get("text", "") if reviews else "")[:300],
            "new_review_count": len(new_reviews),
        }
        HISTORY["seen_review_ids"] = list(seen_ids)[-200:]

        # Crisis triggers
        for r in new_reviews:
            if r.get("rating", 5) <= 2:
                REPORT["alerts"].append({
                    "type": "negative_review",
                    "source": "Google Business",
                    "rating": r.get("rating"),
                    "author": r.get("author_name"),
                    "excerpt": (r.get("text") or "")[:400],
                })
        if prev_rating is not None and result.get("rating") is not None:
            if result["rating"] < prev_rating - 0.05:
                REPORT["alerts"].append({
                    "type": "rating_drop",
                    "source": "Google Business",
                    "from": prev_rating,
                    "to": result["rating"],
                })
    except Exception as e:
        REPORT["reviews"] = {"status": "error", "detail": safe_error(e)}


# ─── 5. Facebook Page recommendations ────────────────────────────────────────

def check_facebook_recommendations():
    page_id = env("FACEBOOK_PAGE_ID")
    token = env("FACEBOOK_PAGE_TOKEN")
    if not page_id or not token:
        REPORT["facebook_recommendations"] = {"status": "skipped", "reason": "Facebook not configured"}
        return
    try:
        resp = requests.get(
            f"{meta.GRAPH}/{page_id}/ratings",
            params={"access_token": token, "fields": "review_text,rating,recommendation_type,created_time,reviewer"},
            timeout=20,
        )
        if resp.status_code != 200:
            try:
                error = resp.json().get("error", {})
            except ValueError:
                error = {}
            if error.get("code") == 283:
                REPORT["facebook_recommendations"] = {
                    "status": "skipped_missing_permission",
                    "reason": (
                        "pages_read_user_content permission is not granted; "
                        "Page publishing and duplicate protection remain active"
                    ),
                }
                return
            REPORT["facebook_recommendations"] = {
                "status": "error",
                "detail": safe_error(f"HTTP {resp.status_code}: {resp.text[:200]}"),
            }
            return
        data = resp.json().get("data", [])
        seen_ids = set(HISTORY.get("seen_fb_recommendation_ids", []))
        new_negative = []
        for item in data:
            rid = f"{item.get('created_time')}|{item.get('reviewer', {}).get('id', '')}"
            is_negative = item.get("recommendation_type") == "negative" or (item.get("rating") is not None and item.get("rating") <= 2)
            if rid not in seen_ids:
                seen_ids.add(rid)
                if is_negative:
                    new_negative.append(item)
        HISTORY["seen_fb_recommendation_ids"] = list(seen_ids)[-200:]
        positive = sum(1 for i in data if i.get("recommendation_type") == "positive")
        negative = sum(1 for i in data if i.get("recommendation_type") == "negative")
        REPORT["facebook_recommendations"] = {
            "status": "ok", "positive": positive, "negative": negative, "total": len(data),
        }
        for item in new_negative:
            REPORT["alerts"].append({
                "type": "negative_facebook_recommendation",
                "source": "Facebook",
                "excerpt": (item.get("review_text") or "")[:400],
            })
    except Exception as e:
        REPORT["facebook_recommendations"] = {"status": "error", "detail": safe_error(e)}


# ─── 6. Web mentions (new pages/articles since last run) ────────────────────

def check_web_mentions():
    api_key = env("SERPAPI_KEY")
    if not api_key:
        REPORT["web_mentions"] = {"status": "skipped", "reason": "SERPAPI_KEY not set"}
        return
    try:
        resp = requests.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google", "q": WEB_MENTION_QUERY,
                "google_domain": GOOGLE_DOMAIN,
                "gl": MARKET_COUNTRY.lower(), "hl": GOOGLE_LANGUAGE,
                "num": 20, "api_key": api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        organic = data.get("organic_results", [])
        current_urls = {r.get("link") for r in organic if r.get("link")}
        seen_urls = set(HISTORY.get("seen_urls", []))

        new_urls = current_urls - seen_urls
        # only alert/report on genuinely new pages once we already have a baseline
        # (skip on the very first run ever, otherwise every result looks "new")
        have_baseline = len(seen_urls) > 0
        new_mentions = [r for r in organic if r.get("link") in new_urls] if have_baseline else []

        HISTORY["seen_urls"] = list(seen_urls | current_urls)[-500:]
        REPORT["web_mentions"] = {
            "status": "ok",
            "total_results_checked": len(organic),
            "new_mentions": [{"title": r.get("title"), "link": r.get("link")} for r in new_mentions],
        }
    except Exception as e:
        if is_serp_quota_error(e):
            activate_serp_backoff()
            REPORT["web_mentions"] = {
                "status": "quota_limited",
                "detail": safe_error(e),
                "retry_on": HISTORY["serp_retry_on_date"],
            }
        else:
            REPORT["web_mentions"] = {"status": "error", "detail": safe_error(e)}


def critical_monitor_failures():
    """Identify configured checks whose failure makes a green run misleading."""
    failures = []
    if env("SERPAPI_KEY"):
        rank_errors = [r for r in REPORT["rank"] if r.get("status") == "error"]
        quota_limited = [
            r for r in REPORT["rank"] if r.get("status") == "quota_limited"
        ]
        if rank_errors:
            failures.append(f"SERP rank: {len(rank_errors)} query errors")
        elif quota_limited:
            failures.append("SERP rank: provider quota/rate limit")
        elif (
            REPORT.get("rank")
            and not rank_measurement_succeeded()
            and not serp_backoff_active()
        ):
            failures.append("SERP rank: no complete fresh measurement")
        if (REPORT.get("web_mentions") or {}).get("status") in {
            "error",
            "quota_limited",
        }:
            failures.append("web mentions")
    if env("OPENAI_API_KEY") and any(
        g.get("status") == "error" for g in REPORT["geo"]
    ):
        failures.append("AI/GEO")
    if env("GOOGLE_PLACES_API_KEY") and (REPORT.get("reviews") or {}).get("status") == "error":
        failures.append("Google reviews")
    if env("FACEBOOK_PAGE_TOKEN") and (
        REPORT.get("facebook_recommendations") or {}
    ).get("status") == "error":
        failures.append("Facebook recommendations")
    failed_tokens = [
        token["platform"]
        for token in REPORT.get("tokens", [])
        if token.get("configured") and not token.get("ok")
    ]
    if failed_tokens:
        failures.append("publisher credentials: " + ", ".join(failed_tokens))
    return failures


# ─── Reporting ────────────────────────────────────────────────────────────────

def format_report_markdown():
    lines = [f"# דוח ניטור - {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]

    lines.append("## דירוג במנועי חיפוש")
    for r in REPORT["rank"]:
        engine = (r.get("engine") or "google").title()
        if r.get("status") == "found":
            lines.append(
                f"- {engine} / {r.get('device', 'unknown')} / "
                f"`{r['keyword']}` → מיקום {r['position_top10']} (עמוד ראשון)"
            )
        elif r.get("status") == "not_in_top10":
            lines.append(
                f"- {engine} / {r.get('device', 'unknown')} / "
                f"`{r['keyword']}` → לא בעשירייה הראשונה"
            )
        elif r.get("status") == "skipped":
            lines.append(f"- דילוג: {r['reason']}")
        else:
            lines.append(
                f"- {engine} / `{r.get('keyword','?')}` → "
                f"שגיאה: {r.get('detail')}"
            )
    lines.append("")

    visibility = (
        (REPORT.get("orchestration") or {})
        .get("visibility_measurement", {})
    )
    lines.append("## P3 — מדידת שליטה לפי מנוע ומשטח")
    serp_surfaces = visibility.get("serp_surfaces", [])
    if serp_surfaces:
        for measurement in serp_surfaces:
            volatility = measurement.get("volatility", {})
            seven = (volatility.get("7d") or {}).get(
                "mean_absolute_position_change"
            )
            twenty_eight = (volatility.get("28d") or {}).get(
                "mean_absolute_position_change"
            )
            lines.append(
                "- "
                f"{str(measurement.get('engine', '?')).title()} / "
                f"{measurement.get('surface', '?')} / "
                f"{measurement.get('interface', '?')} / "
                f"{measurement.get('device', '?')} / "
                f"`{measurement.get('query', '?')}`: "
                f"נשלטות {measurement.get('controlled_count_top10', 0)}, "
                f"רצויות {measurement.get('desired_count_top10', 0)}, "
                f"שליליות {measurement.get('negative_count_top10', 0)}, "
                f"משקל שליטה {measurement.get('weighted_controlled_score', 0)}, "
                f"תנודתיות 7/28 ימים {seven}/{twenty_eight}"
            )
    else:
        lines.append("- אין עדיין דגימת SERP מלאה")
    ai_surfaces = visibility.get("ai_surfaces", [])
    if ai_surfaces:
        for measurement in ai_surfaces:
            lines.append(
                "- "
                f"{measurement.get('engine', '?')} / "
                f"{measurement.get('surface', '?')} / "
                f"{measurement.get('interface', '?')} / "
                f"{measurement.get('model', '?')}: "
                f"זיהוי {measurement.get('identity_accuracy_rate')}, "
                f"דיוק עובדתי {measurement.get('factual_accuracy_rate')}, "
                f"כיסוי נרטיב {measurement.get('desired_narrative_coverage')}, "
                f"ציטוט מקור מאושר "
                f"{measurement.get('approved_source_citation_rate')}, "
                f"מגוון מקורות "
                f"{measurement.get('source_diversity', {}).get('unique_hosts')}, "
                f"מידע מזיק/שגוי "
                f"{measurement.get('harmful_or_incorrect_rate')}, "
                f"יציבות {measurement.get('cross_sample_stability')}"
            )
    else:
        lines.append("- אין עדיין דגימת AI תקינה")
    bing = visibility.get("bing_ai_performance", {})
    lines.append(
        "- Bing AI Performance: "
        f"{bing.get('status', 'no_data')}; "
        f"ציטוטים {bing.get('total_citations', 0)}, "
        f"דפים {bing.get('unique_cited_pages', 0)}, "
        f"שאילתות grounding {bing.get('unique_grounding_queries', 0)}; "
        f"מקור: {bing.get('collection_method', 'authorized_manual_export')}"
    )
    lines.append("")

    opportunities = (
        (REPORT.get("orchestration") or {})
        .get("opportunity_engine", {})
    )
    lines.append("## P4 — הזדמנויות ופעולות מדורגות")
    lines.append(
        "- נוסחה: השפעה צפויה × סמכות הנכס × רלוונטיות לשאילתה "
        "× שליטה ÷ (זמן + עלות + סיכון)"
    )
    selected = opportunities.get("selected_for_preparation", [])
    if selected:
        for item in selected:
            lines.append(
                f"- ציון {item.get('score')} | "
                f"`{item.get('action_type')}` | "
                f"`{item.get('query') or 'ללא שאילתה'}` | "
                f"{item.get('reason') or 'הזדמנות מבוססת מדידה'} | "
                "הכנה אוטונומית; ביצוע ציבורי רק לאחר אישור הפריט"
            )
    else:
        lines.append("- אין פעולה שעברה כעת את ספי הערך, הסיכון והקיבולת")
    lines.append("")

    asset_engine = (
        (REPORT.get("orchestration") or {}).get("asset_engine", {})
    )
    lines.append("## P5 — מועמדים לנכסים חדשים")
    lines.append(
        "- תנאי חובה: ייעוד נפרד, ערך לקורא, תחזוקה בת־קיימא, "
        "מסלול סמכות/התברגות סביר, והיעדר כפילות או doorway"
    )
    candidates = asset_engine.get("candidates", [])
    if candidates:
        for candidate in candidates:
            gate = candidate.get("gate") or {}
            lines.append(
                f"- `{candidate.get('archetype')}` | "
                f"{candidate.get('label')} | "
                f"ציון יצירתי {candidate.get('creative_priority_score')} | "
                f"הכרעה `{gate.get('outcome')}` | "
                f"הוכחות חסרות: {', '.join(gate.get('missing_proofs', [])) or 'אין'}"
            )
    else:
        lines.append(
            f"- אין מועמדים: {asset_engine.get('reason', 'אין פער מדוד')}"
        )
    lines.append("")

    lines.append("## דגימת נוכחות במודל OpenAI (GEO)")
    for g in REPORT["geo"]:
        if g.get("status") == "skipped":
            lines.append(f"- דילוג: {g['reason']}")
        elif g.get("status") == "error":
            lines.append(f"- שגיאה עבור \"{g['prompt']}\": {g['detail']}")
        else:
            mark = "✅ מוזכר" if g["mentions_dr_rofe"] else "❌ לא מוזכר"
            safety = (
                " ⚠️ כולל טענה על פעילות רפואית נוכחית"
                if g.get("active_practice_claim")
                else ""
            )
            if g.get("identity_misinformation"):
                safety += " ⚠️ כולל זיהוי שגוי של האדם או תחום עיסוקו"
            if g.get("knowledge_gap"):
                safety += " ⚠️ חסר מידע מהותי על הזהות או הנכסים הרשמיים"
            lines.append(f"- \"{g['prompt']}\" → {mark}{safety}")
    lines.append("")

    lines.append("## בריאות טוקנים/סשנים")
    for t in REPORT["tokens"]:
        mark = "✅" if t["ok"] else "⚠️"
        lines.append(f"- {mark} {t['platform']}: {t['detail']}")
    lines.append("")

    lines.append("## ביקורות גוגל ביזנס")
    rv = REPORT["reviews"] or {}
    if rv.get("status") == "ok":
        lines.append(f"- {rv['name']}: {rv['rating']}★ ({rv['total_reviews']} ביקורות)")
        if rv.get("new_review_count"):
            lines.append(f"- {rv['new_review_count']} ביקורות חדשות מאז הבדיקה הקודמת")
        if rv.get("latest_review_excerpt"):
            lines.append(f"- ביקורת אחרונה: \"{rv['latest_review_excerpt']}\"")
    elif rv.get("status") == "skipped":
        lines.append(f"- דילוג: {rv['reason']}")
    else:
        lines.append(f"- שגיאה: {rv.get('detail')}")
    lines.append("")

    lines.append("## המלצות פייסבוק")
    fb = REPORT["facebook_recommendations"] or {}
    if fb.get("status") == "ok":
        lines.append(f"- חיוביות: {fb['positive']} | שליליות: {fb['negative']} (מתוך {fb['total']} נבדקו)")
    elif fb.get("status") in {"skipped", "skipped_missing_permission"}:
        lines.append(f"- דילוג: {fb.get('reason')}")
    else:
        lines.append(f"- שגיאה: {fb.get('detail')}")
    lines.append("")

    lines.append("## אזכורים חדשים ברשת")
    wm = REPORT["web_mentions"] or {}
    if wm.get("status") == "ok":
        if wm.get("new_mentions"):
            for m in wm["new_mentions"]:
                lines.append(f"- [{m['title']}]({m['link']})")
        else:
            lines.append("- אין אזכורים חדשים מאז הבדיקה הקודמת")
    elif wm.get("status") == "skipped":
        lines.append(f"- דילוג: {wm['reason']}")
    else:
        lines.append(f"- שגיאה: {wm.get('detail')}")

    return "\n".join(lines)


# Keywords that suggest a review may be harassment/threats rather than a
# genuine service complaint - Google's review policy prohibits this content,
# so these get flagged for one-click removal action, not just noted.
HARASSMENT_KEYWORDS = [
    "כתב אישום", "הושעה", "רישיון", "תא", "כלא", "מאסר", "מטרידנים",
    "אונס", "לא להפיל את הסבון", "יאנס", "תואר דוקטור",
]


def looks_like_harassment(text):
    text = text or ""
    return any(kw in text for kw in HARASSMENT_KEYWORDS)


def format_alert_markdown():
    lines = ["**זוהה שינוי דורש תשומת לב מיידית:**", ""]
    for a in REPORT["alerts"]:
        if a["type"] == "negative_review":
            lines.append(f"### ⚠️ ביקורת שלילית חדשה בגוגל ({a['rating']}★)")
            lines.append(f"מאת: {a.get('author','אנונימי')}")
            lines.append(f"> {a['excerpt']}")
            if looks_like_harassment(a.get("excerpt")):
                lines.append("")
                lines.append("**🚩 התוכן הזה נראה כמו הטרדה/איום, לא ביקורת שירות רגילה - "
                              "זה מפר את מדיניות הביקורות של גוגל ואפשר לדווח עליו להסרה.**")
                lines.append("👉 [דווח כתוכן בלתי הולם](https://business.google.com/reviews) "
                              "(כפתור התלת-נקודה ליד הביקורת הזו → אפשרות סימון כתוכן בלתי הולם)")
                lines.append("")
                lines.append("_גוגל לא חושפת API רשמי לדיווח/הסרת ביקורות - הפעולה חייבת "
                              "להתבצע בלחיצה ידנית דרך הממשק שלהם. זו לא מגבלה של המערכת - "
                              "זו מדיניות של גוגל עצמה. המערכת עושה את כל מה שלפניה: מזהה, "
                              "מתריעה מיידית, ומכינה קישור ישיר - נשאר רק הקליק._")
        elif a["type"] == "rating_drop":
            lines.append(f"### ⚠️ ירידה בדירוג גוגל ביזנס: {a['from']}★ → {a['to']}★")
        elif a["type"] == "negative_facebook_recommendation":
            lines.append("### ⚠️ המלצה שלילית חדשה בפייסבוק")
            lines.append(f"> {a['excerpt']}")
            if looks_like_harassment(a.get("excerpt")):
                lines.append("👉 [פתחו את פייסבוק](https://www.facebook.com/) "
                              "(תלת-נקודה ליד ההמלצה → אפשרות דיווח)")
        elif a["type"] in {
            "ai_active_practice_misinformation",
            "ai_identity_misinformation",
            "ai_knowledge_gap",
            "ai_fact_review_required",
        }:
            issue = {
                "ai_active_practice_misinformation":
                    "טענה שגויה על פעילות רפואית נוכחית",
                "ai_identity_misinformation":
                    f"זיהוי שגוי של {CLIENT_PROFILE['display_name']} או של תחום עיסוקו",
                "ai_knowledge_gap":
                    "חסר מידע מהותי על הזהות או הנכסים הרשמיים",
                "ai_fact_review_required":
                    "התשובה אינה נתמכת במלואה במאגר העובדות המאושר",
            }[a["type"]]
            lines.append(f"### ⚠️ תשובת AI דורשת תיקון: {issue}")
            lines.append(f"שאלה: {a.get('prompt', 'לא צוינה')}")
            lines.append(f"> {a.get('excerpt', 'לא התקבל קטע תשובה')}")
        lines.append("")
    return "\n".join(lines)


def open_github_issue(title, body, labels):
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")
    if not token or not repo:
        print(f"GITHUB_TOKEN/GITHUB_REPOSITORY not set - printing report instead:\n{title}\n{body}")
        return
    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={"title": title, "body": body, "labels": labels},
        timeout=20,
    )
    if resp.status_code >= 300:
        print(f"Failed to open issue: {resp.status_code} {resp.text[:300]}")
    else:
        print(f"Issue opened: {resp.json().get('html_url')}")


def main():
    print(f"=== Reputation Monitor: {CLIENT_PROFILE['display_name']} - Starting ===")
    today_str = date.today().isoformat()
    if serp_checks_due(today_str):
        check_google_rank()
        if serp_backoff_active(today_str):
            REPORT["web_mentions"] = {
                "status": "skipped",
                "reason": "SerpApi retry backoff is active",
                "retry_on": HISTORY.get("serp_retry_on_date"),
            }
        else:
            check_web_mentions()
        if rank_measurement_succeeded():
            HISTORY["last_serp_check_date"] = today_str
    else:
        backoff_reason = (
            "SerpApi retry backoff is active"
            if serp_backoff_active(today_str)
            else "daily SerpApi cadence already completed"
        )
        REPORT["rank"].append({
            "status": "skipped",
            "reason": backoff_reason,
            "retry_on": HISTORY.get("serp_retry_on_date"),
        })
        REPORT["web_mentions"] = {
            "status": "skipped",
            "reason": backoff_reason,
            "retry_on": HISTORY.get("serp_retry_on_date"),
        }
    if ai_checks_due(today_str):
        check_ai_presence()
        if ai_measurement_succeeded():
            HISTORY["last_ai_check_date"] = today_str
    else:
        REPORT["geo"].append({
            "status": "skipped",
            "reason": "daily repeated AI sampling already completed",
        })
    check_token_health()
    check_reviews()
    check_facebook_recommendations()
    search_console_rows = collect_search_console_evidence()

    # Convert raw monitor findings into durable, routed reputation events.
    # This is the active layer: each new risk receives a priority, SLA,
    # approval policy, playbook tasks and (for P0/P1) a crisis room.
    command_center = CommandCenter(COMMAND_CENTER_PATH)
    routed_events = command_center.ingest_monitor_report(REPORT)

    # Re-plan the current high-cadence growth campaign from live evidence.
    observations = load_json_file(GROWTH_OBSERVATIONS_PATH, {})
    registry = load_json_file(ASSET_REGISTRY_PATH, {"assets": []})
    serp_snapshots = [
        {
            "engine": item.get("engine", "google"),
            "surface": item.get("surface", "web_search"),
            "interface": item.get("interface", "search_data_api"),
            "collection_method": item.get(
                "collection_method", "serpapi"
            ),
            "query": item["keyword"],
            "country": item.get("country", "IL"),
            "language": item.get("language", "he"),
            "device": item.get("device", "unknown"),
            "observed_at": REPORT["date"],
            "results": item.get("results", []),
            "features": item.get("features", {}),
        }
        for item in REPORT.get("rank", [])
        if item.get("results")
    ]
    historical_serp_snapshots = [
        {
            "engine": item.get("engine", "google"),
            "surface": item.get("surface", "web_search"),
            "interface": item.get("interface", "search_data_api"),
            "collection_method": item.get(
                "collection_method", "serpapi"
            ),
            "query": item.get("keyword"),
            "country": item.get("country", "IL"),
            "language": item.get("language", "he"),
            "device": item.get("device", "unknown"),
            "observed_at": snapshot.get("date"),
            "results": item.get("results", []),
            "features": item.get("features", {}),
        }
        for snapshot in HISTORY.get("snapshots", [])
        for item in snapshot.get("rank", [])
        if item.get("results")
    ]
    bing_ai_performance = load_json_file(
        BING_AI_PERFORMANCE_PATH, {"rows": []}
    )
    REPORT["orchestration"] = orchestrate_reputation_cycle(
        registry.get("assets", []),
        serp_snapshots,
        ai_snapshots=REPORT.get("geo", []),
        search_console_rows=search_console_rows,
        historical_serp_snapshots=historical_serp_snapshots,
        bing_ai_performance=bing_ai_performance,
        content_freeze=command_center.state.get("content_freeze", False),
    )
    REPORT["bing_ai_performance"] = REPORT["orchestration"][
        "visibility_measurement"
    ]["bing_ai_performance"]
    command_center.state["visibility_measurements"].append({
        "at": REPORT["date"],
        "type": "serp_ai_orchestration",
        "control_maps": REPORT["orchestration"]["control_maps"],
        "ai_visibility": REPORT["orchestration"]["ai_visibility"],
        "visibility_measurement": REPORT["orchestration"][
            "visibility_measurement"
        ],
        "cross_domain_risks": REPORT["orchestration"]["cross_domain_risks"],
        "new_asset_proposals": REPORT["orchestration"]["new_asset_proposals"],
        "asset_engine": REPORT["orchestration"]["asset_engine"],
        "next_best_actions": REPORT["orchestration"]["next_best_actions"][:20],
        "opportunity_engine": REPORT["orchestration"]["opportunity_engine"],
    })
    command_center.state["visibility_measurements"] = (
        command_center.state["visibility_measurements"][-90:]
    )
    command_center.state["opportunities"] = REPORT["orchestration"][
        "opportunity_engine"
    ]["ranked_opportunities"][:100]
    command_center.state["asset_candidates"] = REPORT["orchestration"][
        "asset_engine"
    ]["candidates"][:30]
    command_center._audit(
        "opportunities_replanned",
        REPORT["orchestration"]["opportunity_engine"]["generated_at"],
        {
            "ranked": len(command_center.state["opportunities"]),
            "selected": len(
                REPORT["orchestration"]["opportunity_engine"][
                    "selected_for_preparation"
                ]
            ),
        },
    )
    observations["serp_assets"] = [
        {
            "type": asset.get("type"), "url": asset.get("url"),
            "controlled": asset.get("controlled", False), "status": "active",
            "page_one": asset.get("page_one", False),
            "observed_position": asset.get("observed_position"),
            "tier": asset.get("tier"), "health_status": asset.get("status"),
            "priority": asset.get("priority", 0),
        }
        for asset in registry.get("assets", [])
        if asset.get("tier") in {"A", "B"} and asset.get("priority", 0) >= 55
    ]
    ranked = [
        r for r in REPORT.get("rank", [])
        if r.get("status") in {"found", "not_in_top10"}
    ]
    observations["local_rank_weak"] = any(r.get("status") == "not_in_top10" for r in ranked)
    geo = [g for g in REPORT.get("geo", []) if "mentions_dr_rofe" in g]
    observations["ai_mention_gap"] = any(not g.get("mentions_dr_rofe") for g in geo) if geo else True
    observations["eligible_policy_violations"] = sum(
        1 for alert in REPORT.get("alerts", [])
        if alert.get("type") == "negative_review" and looks_like_harassment(alert.get("excerpt"))
    )
    profile = load_json_file(PROFILE_PATH, {})
    if profile:
        campaign = plan_growth_campaign(profile, observations)
        command_center.state["campaigns"] = [
            c for c in command_center.state["campaigns"] if c.get("id") != campaign["id"]
        ] + [campaign]
        command_center.state["serp_assets"] = observations.get("serp_assets", [])
        command_center._audit("growth_campaign_replanned", campaign["id"], {"tasks": len(campaign["tasks"])})
    command_center.save()
    if routed_events:
        print(f"Command Center: routed {len(routed_events)} new event(s)")
        for event in routed_events:
            print(f"  {event['priority']} score={event['risk_score']} {event['category']} -> {event['id']}")
    else:
        print("Command Center: no new events")

    # Urgent alert - opened immediately, every run, whenever something's detected
    new_alert_events = [
        event for event in routed_events if event.get("source") != "web"
    ]
    if REPORT["alerts"] and new_alert_events:
        alert_md = format_alert_markdown()
        print(alert_md)
        open_github_issue(
            f"🚨 התרעת מוניטין - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            alert_md,
            ["reputation-alert"],
        )
    elif REPORT["alerts"]:
        print("Alert condition already tracked - not opening a duplicate issue.")

    # Full digest - once per calendar day only, to avoid spamming every 2 hours
    if HISTORY.get("last_full_digest_date") != today_str:
        report_md = format_report_markdown()
        print(report_md)
        open_github_issue(f"דוח ניטור {today_str}", report_md, ["monitor-report"])
        HISTORY["last_full_digest_date"] = today_str
    else:
        print("Full digest already posted today - skipping (crisis checks still ran above).")

    # Persist history/state
    HISTORY.setdefault("snapshots", []).append(REPORT)
    save_history(HISTORY)

    with open("monitor_report.json", "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    failures = critical_monitor_failures()
    if failures:
        print("MONITOR DEGRADED: " + ", ".join(failures))
        raise SystemExit(2)
    print("=== Done ===")


if __name__ == "__main__":
    main()
