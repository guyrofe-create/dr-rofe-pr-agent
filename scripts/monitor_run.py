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
from datetime import datetime, date
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta, twitter, tumblr, telegram, blogger, pinterest

SITE_DOMAIN = "guyrofe.com"
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "reputation_history.json")

KEYWORDS = [
    "גינקולוג תל אביב",
    "אנדומטריוזיס תל אביב",
    "לפרוסקופיה גינקולוגית",
    "דר גיא רופא",
    "כאבי אגן כרוניים גינקולוג",
]

GEO_PROMPTS = [
    "מי הוא דר גיא רופא, גינקולוג?",
    "המלץ על גינקולוג מומחה לאנדומטריוזיס בתל אביב",
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
            REPORT["rank"].append({"keyword": kw, "status": "error", "detail": str(e)})


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
            REPORT["geo"].append({"prompt": prompt, "mentions_dr_rofe": mentioned, "excerpt": answer[:200]})
        except Exception as e:
            REPORT["geo"].append({"prompt": prompt, "status": "error", "detail": str(e)})


# ─── 3. Token / session health ───────────────────────────────────────────────

def check_token_health():
    checks = [
        ("Facebook", meta.check_token_health),
        ("Twitter/X", twitter.check_token_health),
        ("Tumblr", tumblr.check_token_health),
        ("Telegram", telegram.check_token_health),
        ("Blogger", blogger.check_token_health),
        ("Pinterest", pinterest.check_token_health),
    ]
    for name, fn in checks:
        try:
            ok, detail = fn()
            REPORT["tokens"].append({"platform": name, "ok": ok, "detail": detail})
        except Exception as e:
            REPORT["tokens"].append({"platform": name, "ok": False, "detail": str(e)})

    medium_sid = env("MEDIUM_SID")
    medium_token = env("MEDIUM_TOKEN")
    if medium_token:
        REPORT["tokens"].append({"platform": "Medium", "ok": True, "detail": "using MEDIUM_TOKEN (API)"})
    elif medium_sid:
        try:
            resp = requests.get(
                "https://medium.com/me/stories/drafts",
                cookies={"sid": medium_sid}, timeout=15, allow_redirects=True,
            )
            expired = "signin" in resp.url or "login" in resp.url
            REPORT["tokens"].append({
                "platform": "Medium", "ok": not expired,
                "detail": "session expired - refresh MEDIUM_SID" if expired else "session valid",
            })
        except Exception as e:
            REPORT["tokens"].append({"platform": "Medium", "ok": False, "detail": str(e)})
    else:
        REPORT["tokens"].append({"platform": "Medium", "ok": False, "detail": "not configured"})


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
        REPORT["reviews"] = {"status": "error", "detail": str(e)}


# ─── 5. Facebook Page recommendations ────────────────────────────────────────

def check_facebook_recommendations():
    page_id = env("FACEBOOK_PAGE_ID")
    token = env("FACEBOOK_PAGE_TOKEN")
    if not page_id or not token:
        REPORT["facebook_recommendations"] = {"status": "skipped", "reason": "Facebook not configured"}
        return
    try:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{page_id}/ratings",
            params={"access_token": token, "fields": "review_text,rating,recommendation_type,created_time,reviewer"},
            timeout=20,
        )
        if resp.status_code != 200:
            REPORT["facebook_recommendations"] = {"status": "error", "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
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
        REPORT["facebook_recommendations"] = {"status": "error", "detail": str(e)}


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
        REPORT["web_mentions"] = {"status": "error", "detail": str(e)}


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

    lines.append("## נוכחות במנועי AI (GEO)")
    for g in REPORT["geo"]:
        if g.get("status") == "skipped":
            lines.append(f"- דילוג: {g['reason']}")
        elif g.get("status") == "error":
            lines.append(f"- שגיאה עבור \"{g['prompt']}\": {g['detail']}")
        else:
            mark = "✅ מוזכר" if g["mentions_dr_rofe"] else "❌ לא מוזכר"
            lines.append(f"- \"{g['prompt']}\" → {mark}")
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
    elif fb.get("status") == "skipped":
        lines.append(f"- דילוג: {fb['reason']}")
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
    check_google_rank()
    check_ai_presence()
    check_token_health()
    check_reviews()
    check_facebook_recommendations()
    check_web_mentions()

    # Urgent alert - opened immediately, every run, whenever something's detected
    if REPORT["alerts"]:
        alert_md = format_alert_markdown()
        print(alert_md)
        open_github_issue(
            f"🚨 התרעת מוניטין - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            alert_md,
            ["reputation-alert"],
        )

    # Full digest - once per calendar day only, to avoid spamming every 2 hours
    today_str = date.today().isoformat()
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
    print("=== Done ===")


if __name__ == "__main__":
    main()

