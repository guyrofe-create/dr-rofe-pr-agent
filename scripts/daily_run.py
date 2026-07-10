#!/usr/bin/env python3
"""
Dr. Guy Rofe - Autonomous PR Agent
Runs on GitHub Actions (cloud) every Mon/Wed/Fri at 09:00 Israel time.
No Mac required. Fully autonomous.

Supports TWO publishing methods:
  Method A - API Token:  set MEDIUM_TOKEN secret
  Method B - Browser:    set MEDIUM_EMAIL + MEDIUM_PASSWORD secrets (no token needed)
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

# ─── Method B: Publish via Browser (no token needed) ─────────────────────────

def publish_via_browser(email, password, title, content_md):
    log("Using Method B: Browser automation (Playwright)")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )

        # Step 1: Login
        log("Navigating to Medium login...")
        page.goto("https://medium.com/m/signin", wait_until="networkidle")
        time.sleep(2)

        # Click "Sign in with email"
        try:
            page.click("text=Sign in with email", timeout=5000)
            time.sleep(1)
            page.fill('input[type="email"]', email)
            page.click("text=Continue")
            time.sleep(2)
            # Medium sends a magic link - fallback to Google
            log("Email magic link sent - trying Google login instead")
        except:
            pass

        # Try Google login
        try:
            page.goto("https://medium.com/m/signin", wait_until="networkidle")
            page.click("text=Sign in with Google", timeout=5000)
            time.sleep(2)
            # Fill Google email
            page.fill('input[type="email"]', email)
            page.keyboard.press("Enter")
            time.sleep(2)
            page.fill('input[type="password"]', password)
            page.keyboard.press("Enter")
            time.sleep(4)
            log("Google login attempted")
        except Exception as e:
            log(f"Login attempt: {e}")

        # Step 2: Open new story editor
        log("Opening new story editor...")
        page.goto("https://medium.com/new-story", wait_until="networkidle")
        time.sleep(3)

        # Step 3: Type title
        log("Typing title...")
        title_el = page.locator('h1[data-placeholder="Title"]').first
        title_el.click()
        title_el.type(title, delay=20)
        time.sleep(1)

        # Step 4: Type content (simplified - plain text)
        log("Typing article content...")
        page.keyboard.press("Enter")
        # Convert markdown to plain text for editor
        plain_content = content_md.replace("# ", "").replace("## ", "").replace("**", "")
        page.keyboard.type(plain_content[:3000], delay=5)
        time.sleep(2)

        # Step 5: Publish
        log("Publishing...")
        try:
            page.click("text=Publish", timeout=5000)
            time.sleep(2)
            page.click("text=Publish now", timeout=5000)
            time.sleep(3)
        except Exception as e:
            log(f"Publish click: {e}")

        url = page.url
        browser.close()
        log(f"Done. Final URL: {url}")
        return url

# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    log("=== Dr. Rofe PR Agent - Starting ===")
    log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")

    # Determine publish method
    medium_token = os.environ.get("MEDIUM_TOKEN")
    medium_email = os.environ.get("MEDIUM_EMAIL")
    medium_password = os.environ.get("MEDIUM_PASSWORD")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if not openai_key:
        log("ERROR: OPENAI_API_KEY secret is not set")
        exit(1)

    if not medium_token and not (medium_email and medium_password):
        log("ERROR: Set either MEDIUM_TOKEN or both MEDIUM_EMAIL + MEDIUM_PASSWORD")
        exit(1)

    # Pick topic
    week = datetime.now().isocalendar()[1]
    day = datetime.now().weekday()
    topic = TOPICS[(week * 3 + day) % len(TOPICS)]
    log(f"Topic: {topic}")

    # Generate content
    log("Generating article via GPT-4o...")
    title, content = generate_article(topic)
    log(f"Generated: {len(content)} chars")

    # Publish
    if medium_token:
        url = publish_via_api(medium_token, title, content)
    else:
        url = publish_via_browser(medium_email, medium_password, title, content)

    log(f"Published: {url}")
    log("=== Done ===")

    with open("run_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))

if __name__ == "__main__":
    main()
