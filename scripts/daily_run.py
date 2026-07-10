#!/usr/bin/env python3
"""
Dr. Guy Rofe - Autonomous PR Agent
Runs on GitHub Actions every Mon/Wed/Fri at 09:00 Israel time.
No Mac required. Fully autonomous.

Auth methods (in priority order):
  1. MEDIUM_TOKEN  — Medium API token (if available)
  2. MEDIUM_SID    — Medium session cookie (login once via browser, paste sid value)
"""

from openai import OpenAI
import requests
import os
import time
from datetime import datetime

TOPICS = [
    "כאבי אגן כרוניים אצל נשים - מתי לפנות לגינקולוג?",
    "לפרוסקופיה גינקולוגית - מדריך מלא למטופלת",
    "אנדומטריוזיס ופוריות - מה הקשר ומה ניתן לעשות?",
    "מיומות ברחם - מתי צריך ניתוח ומתי לא?",
    "תסמונת השחלות הפוליציסטיות - תסמינים, אבחון וטיפול",
    "כאבי מחזור קשים - כמה כאב זה נורמלי?",
    "ניתוח גינקולוגי מינימלי פולשני - יתרונות, זמן החלמה, סיכונים",
    "גיל המעבר - מה כל אישה צריכה לדעת על גופה",
    "דימומים חריגים - מה הם אומרים על הבריאות שלך?",
    "שאלות שנשים לא שואלות את הגינקולוג - ועוצמה לשאול אותן",
]

TAGS = ["גינקולוגיה", "בריאות אשה", "אנדומטריוזיס", "לפרוסקופיה", "דר גיא רופא"]
LOG_LINES = []

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_LINES.append(line)

# ─── Content Generation ──────────────────────────────────────────────────────

def generate_article(topic):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = f"""כתוב מאמר רפואי מקצועי בעברית עבור דר גיא רופא, גינקולוג מומחה לאנדומטריוזיס ולפרוסקופיה בתל אביב.

נושא: {topic}

דרישות:
- אורך: 700-900 מילים
- שפה: עברית מקצועית אך נגישה לקהל רחב
- מבנה: כותרת ראשית H1, מבוא, 3-4 סעיפים עם כותרות H2, סיכום
- CTA בסוף: לייעוץ עם דר גיא רופא: guyrofe.com
- כלול: דר גיא רופא, גינקולוג, אנדומטריוזיס, לפרוסקופיה, תל אביב
- פורמט: Markdown

החזר רק את המאמר."""
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
    )
    content = response.choices[0].message.content
    lines = content.strip().split("\n")
    title = lines[0].lstrip("#").strip() if lines else topic
    return title, content

# ─── Method A: Publish via API Token ─────────────────────────────────────────

def publish_via_api(token, title, content):
    log("Using Method A: Medium API Token")
    resp = requests.get(
        "https://api.medium.com/v1/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    user_id = resp.json()["data"]["id"]
    resp = requests.post(
        f"https://api.medium.com/v1/users/{user_id}/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "title": title,
            "contentFormat": "markdown",
            "content": content,
            "tags": TAGS,
            "publishStatus": "public",
            "license": "all-rights-reserved",
            "notifyFollowers": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    result = resp.json()
    if "data" in result:
        return result["data"].get("url", "published")
    raise Exception(f"API error: {result}")

# ─── Method B: Publish via Session Cookie (no password needed) ───────────────

def publish_via_cookie(sid, title, content_md):
    log("Using Method B: Session cookie (sid)")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )

        # Inject the session cookie — no login needed
        context.add_cookies([{
            "name": "sid",
            "value": sid,
            "domain": ".medium.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
        }])

        page = context.new_page()

        # Verify login worked
        log("Verifying session...")
        page.goto("https://medium.com/me/stories/drafts", wait_until="networkidle")
        time.sleep(2)
        if "signin" in page.url or "login" in page.url:
            raise Exception("Session cookie expired — please refresh MEDIUM_SID secret")
        log("Session valid. Opening editor...")

        # Open new story
        page.goto("https://medium.com/new-story", wait_until="networkidle")
        time.sleep(3)

        # Type title
        log("Typing title...")
        title_el = page.locator('h1[data-placeholder="Title"]').first
        title_el.click()
        title_el.type(title, delay=30)
        time.sleep(1)
        page.keyboard.press("Enter")
        time.sleep(1)

        # Type content (plain text, stripped of markdown symbols)
        log("Typing content...")
        plain = content_md
        for sym in ["# ", "## ", "### ", "**", "__", "- "]:
            plain = plain.replace(sym, "")
        page.keyboard.type(plain[:4000], delay=3)
        time.sleep(2)

        # Publish
        log("Publishing...")
        try:
            page.click("button:has-text('Publish')", timeout=8000)
            time.sleep(2)
            page.click("button:has-text('Publish now')", timeout=5000)
            time.sleep(4)
        except Exception as e:
            log(f"Publish button: {e}")

        url = page.url
        browser.close()
        log(f"Done. URL: {url}")
        return url

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    log("=== Dr. Rofe PR Agent - Starting ===")
    log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")

    openai_key = os.environ.get("OPENAI_API_KEY")
    medium_token = os.environ.get("MEDIUM_TOKEN")
    medium_sid = os.environ.get("MEDIUM_SID")

    if not openai_key:
        log("ERROR: OPENAI_API_KEY secret is not set")
        exit(1)

    if not medium_token and not medium_sid:
        log("ERROR: Set either MEDIUM_TOKEN or MEDIUM_SID in GitHub Secrets")
        exit(1)

    # Pick topic by week+day rotation
    week = datetime.now().isocalendar()[1]
    day = datetime.now().weekday()
    topic = TOPICS[(week * 3 + day) % len(TOPICS)]
    log(f"Topic: {topic}")

    # Generate article
    log("Generating article via GPT-4o...")
    title, content = generate_article(topic)
    log(f"Generated {len(content)} chars")

    # Publish
    if medium_token:
        url = publish_via_api(medium_token, title, content)
    else:
        url = publish_via_cookie(medium_sid, title, content)

    log(f"Published: {url}")
    log("=== Done ===")

    with open("run_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))

if __name__ == "__main__":
    main()
