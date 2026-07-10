#!/usr/bin/env python3
"""
Dr. Guy Rofe - Autonomous PR Agent
Runs on GitHub Actions (cloud) every Mon/Wed/Fri at 09:00 Israel time.
No Mac required. Fully autonomous.
"""

import anthropic
import requests
import os
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

def generate_article(topic):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
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
    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}]
    )
    content = message.content[0].text
    lines = content.strip().split("\n")
    title = lines[0].lstrip("#").strip() if lines else topic
    return title, content

def get_medium_user_id(token):
    resp = requests.get(
        "https://api.medium.com/v1/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["data"]["id"]

def publish_to_medium(token, title, content):
    user_id = get_medium_user_id(token)
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
    return resp.json()

def main():
    log("=== Dr. Rofe PR Agent - Starting ===")
    log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    token = os.environ.get("MEDIUM_TOKEN")
    if not token:
        log("ERROR: MEDIUM_TOKEN secret is not set")
        exit(1)
    week = datetime.now().isocalendar()[1]
    day = datetime.now().weekday()
    topic_index = (week * 3 + day) % len(TOPICS)
    topic = TOPICS[topic_index]
    log(f"Topic: {topic}")
    log("Generating article via Claude API...")
    title, content = generate_article(topic)
    log(f"Generated: {len(content)} chars")
    log("Publishing to Medium...")
    result = publish_to_medium(token, title, content)
    if "data" in result:
        url = result["data"].get("url", "unknown")
        log(f"Published: {url}")
    else:
        log(f"Medium error: {result}")
        exit(1)
    log("=== Done ===")
    with open("run_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))

if __name__ == "__main__":
    main()
