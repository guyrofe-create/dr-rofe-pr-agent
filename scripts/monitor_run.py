#!/usr/bin/env python3
"""
Dr. Guy Rofe - Reputation & Visibility Monitor
Runs daily on GitHub Actions (see .github/workflows/monitor.yml).

Checks, in order:
  1. Google rank      - target keywords vs guyrofe.com (SerpApi - live Google Search)
  2. AI/GEO presence   - does ChatGPT already know Dr. Guy Rofe when asked
  3. Token/session health - every configured publisher credential, still valid?
  4. Google Business reviews - rating & review count (Google Places API)

Everything is reported by opening a GitHub Issue on this repo (label
"monitor-report"), so history lives in Issues - no extra secrets, no state
file, no email setup required.
"""
import os
import sys
import json
import requests
from datetime import datetime
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta, twitter, tumblr, telegram, blogger, pinterest

SITE_DOMAIN = "guyrofe.com"

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

REPORT = {"rank": [], "geo": [], "tokens": [], "reviews": None, "errors": []}


def env(name):
    return os.environ.get(name, "").strip() or None


# ─── 1. Google rank via Custom Search JSON API ───────────────────────────────

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
                    "engine": "google",
                    "q": kw,
                    "google_domain": "google.co.il",
                    "gl": "il",
                    "hl": "iw",
                    "num": 10,
                    "api_key": api_key,
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
                "keyword": kw,
                "position_top10": position,
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
            REPORT["geo"].append({
                "prompt": prompt,
                "mentions_dr_rofe": mentioned,
                "excerpt": answer[:200],
            })
        except Exception as e:
            REPORT["geo"].append({"prompt": prompt, "status": "error", "detail": str(e)})


# ─── 3. Token / session health for every configured publisher ───────────────

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

    # Medium uses a session cookie (SID) rather than a bearer token - check
    # separately since it has no dedicated publisher module (lives in daily_run.py).
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


# ─── 4. Google Business reviews via Places API ───────────────────────────────

def check_reviews():
    api_key = env("GOOGLE_PLACES_API_KEY")
    place_id = env("GOOGLE_PLACE_ID")
    if not api_key or not place_id:
        REPORT["reviews"] = {"status": "skipped", "reason": "GOOGLE_PLACES_API_KEY / GOOGLE_PLACE_ID not set"}
        return
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/place/details/json",
            params={"place_id": place_id, "fields": "name,rating,user_ratings_total,reviews", "key": api_key},
            timeout=20,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        REPORT["reviews"] = {
            "status": "ok",
            "name": result.get("name"),
            "rating": result.get("rating"),
            "total_reviews": result.get("user_ratings_total"),
            "latest_review_excerpt": (result.get("reviews") or [{}])[0].get("text", "")[:200],
        }
    except Exception as e:
        REPORT["reviews"] = {"status": "error", "detail": str(e)}


# ─── Reporting: open a GitHub Issue with the full findings ───────────────────

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
        if rv.get("latest_review_excerpt"):
            lines.append(f"- ביקורת אחרונה: \"{rv['latest_review_excerpt']}\"")
    elif rv.get("status") == "skipped":
        lines.append(f"- דילוג: {rv['reason']}")
    else:
        lines.append(f"- שגיאה: {rv.get('detail')}")

    return "\n".join(lines)


def open_github_issue(body):
    token = env("GITHUB_TOKEN")
    repo = env("GITHUB_REPOSITORY")  # "owner/name", auto-set by Actions
    if not token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY not set - printing report instead:\n")
        print(body)
        return
    resp = requests.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={
            "title": f"דוח ניטור {datetime.now().strftime('%Y-%m-%d')}",
            "body": body,
            "labels": ["monitor-report"],
        },
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

    report_md = format_report_markdown()
    print(report_md)
    open_github_issue(report_md)

    with open("monitor_report.json", "w", encoding="utf-8") as f:
        json.dump(REPORT, f, ensure_ascii=False, indent=2)
    print("=== Done ===")


if __name__ == "__main__":
    main()

