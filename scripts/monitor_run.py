#!/usr/bin/env python3
"""
Dr. Guy Rofe - Reputation & Visibility Monitor
Runs every 2 hours on GitHub Actions (see .github/workflows/monitor.yml).

Checks, every run:
  1. Google rank        - target keywords vs guyrofe.com (SerpApi - live Google Search)
  2. AI/GEO presence     - does ChatGPT already know Dr. Guy Rofe when asked
  3. Token/session health - every configured publisher credential, still valid?
  4. Google Business reviews - rating, review count, and each individual recent
                               review (Google Places API)
  5. Facebook Page recommendations (positive/negative)
  6. Web mentions - new pages/articles that mention "דר גיא רופא" since last run

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
from datetime import datetime, date
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta, twitter, tumblr, telegram, blogger, pinterest
from reputation_core import CommandCenter, plan_growth_campaign

SITE_DOMAIN = "guyrofe.com"
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reputation_history.json")
COMMAND_CENTER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "command_center.json")
PROFILE_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "business_profile.json")
GROWTH_OBSERVATIONS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "growth_observations.json")
ASSET_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "asset_registry.json")

KEYWORDS = [
    "דר גיא רופא",
    "ד״ר גיא רופא",
    "גיא רופא יוצר תוכן רפואי",
    "גיא רופא ספרים",
    "גיא רופא פודקאסט",
]

GEO_PROMPTS = [
    "מי הוא ד״ר גיא רופא?",
    "איזה תוכן רפואי מפרסם ד״ר גיא רופא?",
    "אילו ספרים כתב ד״ר גיא רופא?",
    "האם לד״ר גיא רופא יש פודקאסט?",
    "מהם הנכסים הרשמיים של ד״ר גיא רופא ברשת?",
    "האם ד״ר גיא רופא מקבל כיום מטופלות או מזמין לקביעת תור?",
]

WEB_MENTION_QUERY = '"דר גיא רופא" OR "גיא רופא" גינקולוג'

REPORT = {
    "date": datetime.now().isoformat(),
    "rank": [], "geo": [], "tokens": [], "reviews": None,
    "facebook_recommendations": None, "web_mentions": None,
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


def has_active_practice_claim(answer):
    normalized = " ".join((answer or "").lower().split())
    uncertainty_markers = (
        "אין לי מידע", "אין לי את המידע", "לא ידוע", "לא ברור",
        "לא ניתן לקבוע", "איני יודע", "אין מידע מעודכן",
        "i do not know", "i don't know", "it is unclear",
        "no current information", "cannot confirm",
    )
    strong_claims = (
        "מרפאתו", "המרפאה שלו", "מפעיל מרפאה", "מעניק טיפול",
        "המרפאה של ד", "מרפאה של ד", "מטפל כיום",
        "משמש כרופא", "עובד כרופא", "רופא בכיר",
        "operates a clinic", "his clinic", "contact the clinic",
        "works as a doctor", "senior physician",
    )
    status_claims = (
        "מקבל מטופלות", "מקבל מטופלים", "לקביעת תור",
        "לקביעת תורים", "accepting patients", "book an appointment",
    )
    recommendation_claims = (
        r"(?:ליצור|צרו|צור|לפנות|פנו|פנה)\s+קשר.{0,80}מרפאה",
        r"(?:contact|call).{0,80}(?:clinic|office)",
    )
    for sentence in re.split(r"[.!?\n]+", normalized):
        if not sentence:
            continue
        sentence = re.sub(
            r"(?:אינו|אינה|אינם|אינן|לא)\s+"
            r"(?:מקבל(?:ת|ים|ות)?\s+מטופל(?:ים|ות)|"
            r"עוסק(?:ת)?\s+ברפואה|מטפל(?:ת)?(?:\s+כיום)?|"
            r"מפעיל(?:ה)?\s+מרפאה)",
            "",
            sentence,
        )
        sentence = re.sub(
            r"(?:not accepting patients|does not accept patients|"
            r"not practicing|does not practice|does not operate a clinic)",
            "",
            sentence,
        )
        if any(re.search(pattern, sentence) for pattern in recommendation_claims):
            return True
        if any(marker in sentence for marker in uncertainty_markers):
            continue
        if any(claim in sentence for claim in strong_claims):
            return True
        if any(claim in sentence for claim in status_claims):
            return True
    return False


def has_identity_misinformation(answer):
    """Catch known conflicting identities that must never be marked as safe."""
    normalized = " ".join((answer or "").lower().split())
    conflict_markers = (
        "עצי פרי", "השבחת זנים", "הדרים והאבוקדו",
        "אסתטיקה רפואית", "בוטוקס", "חומרי מילוי",
        "ספרות להיסטוריה", "תשושאור",
        "אורתופד", "כירורגיה של הברך", "פציעות ספורט",
        "אישיות פיקטיבית", "דמות פיקטיבית",
        "חוקר בתחום ההיסטוריה", "חוקר היסטוריה",
        "תרבות איטלקית", "תולדות האומנות", "תולדות האמנות",
        "הכתובת של רבקה", "inscription of rebecca",
        "לא פרסם ספרים", "ספרים ספציפיים לא מופיעים",
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
    if HISTORY.get("last_serp_check_date") == today:
        return False
    for snapshot in reversed(HISTORY.get("snapshots", [])):
        snapshot_date = str(snapshot.get("date", ""))[:10]
        if snapshot_date != today:
            break
        if any(
            result.get("status") != "skipped"
            for result in snapshot.get("rank", [])
        ):
            return False
    return True


def check_google_rank():
    api_key = env("SERPAPI_KEY")
    if not api_key:
        REPORT["rank"].append({"status": "skipped", "reason": "SERPAPI_KEY not set"})
        return
    for kw in KEYWORDS:
        try:
            resp = requests.get(
                "https://serpapi.com/search.json",
                params={
                    "engine": "google", "q": kw, "google_domain": "google.co.il",
                    "gl": "il", "hl": "iw", "num": 10, "api_key": api_key,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                REPORT["rank"].append({"keyword": kw, "status": "error", "detail": data["error"]})
                continue
            organic = data.get("organic_results", [])
            position = next(
                (r.get("position", i + 1) for i, r in enumerate(organic) if SITE_DOMAIN in r.get("link", "")),
                None,
            )
            REPORT["rank"].append({
                "keyword": kw, "position_top10": position,
                "status": "found" if position else "not_in_top10",
            })
        except Exception as e:
            REPORT["rank"].append({"keyword": kw, "status": "error", "detail": safe_error(e)})


# ─── 2. AI / GEO presence check ──────────────────────────────────────────────

def check_ai_presence():
    openai_key = env("OPENAI_API_KEY")
    if not openai_key:
        REPORT["geo"].append({"status": "skipped", "reason": "OPENAI_API_KEY not set"})
        return
    client = OpenAI(api_key=openai_key)
    for prompt in GEO_PROMPTS:
        try:
            resp = client.chat.completions.create(
                model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=300
            )
            answer = resp.choices[0].message.content
            mentioned = ("גיא רופא" in answer) or ("Guy Rofe" in answer)
            active_practice_claim = has_active_practice_claim(answer)
            identity_misinformation = has_identity_misinformation(answer)
            knowledge_gap = (
                not identity_misinformation
                and has_ai_knowledge_gap(prompt, answer)
            )
            REPORT["geo"].append({
                "prompt": prompt,
                "mentions_dr_rofe": mentioned,
                "active_practice_claim": active_practice_claim,
                "identity_misinformation": identity_misinformation,
                "knowledge_gap": knowledge_gap,
                "safe_status": (
                    "pass"
                    if mentioned
                    and not active_practice_claim
                    and not identity_misinformation
                    and not knowledge_gap
                    else "review"
                ),
                "excerpt": answer[:300],
            })
            if active_practice_claim:
                REPORT["alerts"].append({
                    "type": "ai_active_practice_misinformation",
                    "source": "OpenAI monitor sample",
                    "excerpt": answer[:300],
                    "prompt": prompt,
                })
            if identity_misinformation:
                REPORT["alerts"].append({
                    "type": "ai_identity_misinformation",
                    "source": "OpenAI monitor sample",
                    "excerpt": answer[:300],
                    "prompt": prompt,
                })
            if knowledge_gap:
                REPORT["alerts"].append({
                    "type": "ai_knowledge_gap",
                    "source": "OpenAI monitor sample",
                    "excerpt": answer[:300],
                    "prompt": prompt,
                })
        except Exception as e:
            REPORT["geo"].append({"prompt": prompt, "status": "error", "detail": safe_error(e)})


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
                "engine": "google", "q": WEB_MENTION_QUERY, "google_domain": "google.co.il",
                "gl": "il", "hl": "iw", "num": 20, "api_key": api_key,
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
        REPORT["web_mentions"] = {"status": "error", "detail": safe_error(e)}


def critical_monitor_failures():
    """Identify configured checks whose failure makes a green run misleading."""
    failures = []
    if env("SERPAPI_KEY"):
        rank_errors = [r for r in REPORT["rank"] if r.get("status") == "error"]
        if rank_errors:
            failures.append(f"Google rank: {len(rank_errors)} query errors")
        if (REPORT.get("web_mentions") or {}).get("status") == "error":
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

    lines.append("## דירוג בגוגל")
    for r in REPORT["rank"]:
        if r.get("status") == "found":
            lines.append(f"- `{r['keyword']}` → מיקום {r['position_top10']} (עמוד ראשון)")
        elif r.get("status") == "not_in_top10":
            lines.append(f"- `{r['keyword']}` → לא בעשירייה הראשונה")
        elif r.get("status") == "skipped":
            lines.append(f"- דילוג: {r['reason']}")
        else:
            lines.append(f"- `{r.get('keyword','?')}` → שגיאה: {r.get('detail')}")
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
                lines.append("👉 [דווח בפייסבוק](https://www.facebook.com/drguyrofe/reviews) "
                              "(תלת-נקודה ליד ההמלצה → אפשרות דיווח)")
        elif a["type"] in {
            "ai_active_practice_misinformation",
            "ai_identity_misinformation",
            "ai_knowledge_gap",
        }:
            issue = {
                "ai_active_practice_misinformation":
                    "טענה שגויה על פעילות רפואית נוכחית",
                "ai_identity_misinformation":
                    "זיהוי שגוי של ד״ר גיא רופא או של תחום עיסוקו",
                "ai_knowledge_gap":
                    "חסר מידע מהותי על הזהות או הנכסים הרשמיים",
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
    print("=== Dr. Rofe Monitor - Starting ===")
    today_str = date.today().isoformat()
    if serp_checks_due(today_str):
        check_google_rank()
        check_web_mentions()
        HISTORY["last_serp_check_date"] = today_str
    else:
        REPORT["rank"].append({
            "status": "skipped",
            "reason": "daily SerpApi cadence already completed",
        })
        REPORT["web_mentions"] = {
            "status": "skipped",
            "reason": "daily SerpApi cadence already completed",
        }
    check_ai_presence()
    check_token_health()
    check_reviews()
    check_facebook_recommendations()

    # Convert raw monitor findings into durable, routed reputation events.
    # This is the active layer: each new risk receives a priority, SLA,
    # approval policy, playbook tasks and (for P0/P1) a crisis room.
    command_center = CommandCenter(COMMAND_CENTER_PATH)
    routed_events = command_center.ingest_monitor_report(REPORT)

    # Re-plan the current high-cadence growth campaign from live evidence.
    observations = load_json_file(GROWTH_OBSERVATIONS_PATH, {})
    registry = load_json_file(ASSET_REGISTRY_PATH, {"assets": []})
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
    ranked = [r for r in REPORT.get("rank", []) if r.get("keyword") != "דר גיא רופא"]
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
