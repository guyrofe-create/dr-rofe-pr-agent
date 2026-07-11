#!/usr/bin/env python3
"""
Dr. Guy Rofe - Social Distribution Layer
Runs on GitHub Actions (see .github/workflows/social_publish.yml).

Generates a short social post from the rotating topic list and pushes it to
every platform that has credentials configured. Platforms without credentials
are skipped (not failed) so partial setup never blocks the others. Platforms
with no safe posting API get a ready-to-paste draft file instead.
"""
import os
import sys
from datetime import datetime
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta, twitter, tumblr, telegram, blogger, pinterest, manual_draft

SITE_URL = "https://guyrofe.com"

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

LOG_LINES = []


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_LINES.append(line)


def generate_social_post(topic):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = f"""כתוב פוסט קצר לרשתות חברתיות (עד 120 מילים) בעברית עבור דר גיא רופא,
גינקולוג מומחה לאנדומטריוזיס ולפרוסקופיה בתל אביב, על הנושא: {topic}

טון: חם, מקצועי, נגיש. שורה ראשונה = הוק שמושך תשומת לב.
אל תשתמש בהאשטגים. אל תשתמש בכותרות markdown.
השורה האחרונה תהיה קריאה לפעולה קצרה לפנייה לייעוץ."""
    resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=400
    )
    body = resp.choices[0].message.content.strip()
    title = topic
    return title, body


def try_publish(name, is_configured_fn, publish_fn, *args):
    if not is_configured_fn():
        log(f"{name}: SKIPPED (not configured)")
        return None
    try:
        result_url = publish_fn(*args)
        log(f"{name}: OK -> {result_url}")
        return result_url
    except Exception as e:
        log(f"{name}: FAILED -> {e}")
        return None


def main():
    log("=== Dr. Rofe Social Distribution - Starting ===")

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        log("ERROR: OPENAI_API_KEY secret is not set")
        sys.exit(1)

    week = datetime.now().isocalendar()[1]
    day = datetime.now().weekday()
    topic = TOPICS[(week * 3 + day) % len(TOPICS)]
    log(f"Topic: {topic}")

    title, body = generate_social_post(topic)
    log(f"Generated post ({len(body)} chars)")

    # Tier 1: real APIs, text-only platforms
    try_publish("Facebook", meta.facebook_is_configured, meta.publish_facebook, title, body, SITE_URL)
    try_publish("Twitter/X", twitter.is_configured, twitter.publish, title, body, SITE_URL)
    try_publish("Tumblr", tumblr.is_configured, tumblr.publish, title, body, SITE_URL)
    try_publish("Telegram", telegram.is_configured, telegram.publish, title, body, SITE_URL)
    try_publish("Blogger", blogger.is_configured, blogger.publish, title, f"<p>{body}</p>", SITE_URL)

    # Tier 1b: need an image (skipped automatically if IMAGE_URL not set)
    image_url = os.environ.get("SOCIAL_IMAGE_URL")
    if image_url:
        try_publish("Instagram", meta.instagram_is_configured, meta.publish_instagram, title, body, SITE_URL, image_url)
        try_publish("Pinterest", pinterest.is_configured, pinterest.publish, title, body, SITE_URL, image_url)
    else:
        log("Instagram: SKIPPED (no SOCIAL_IMAGE_URL set)")
        log("Pinterest: SKIPPED (no SOCIAL_IMAGE_URL set)")

    # Tier 3: no safe posting API - write a ready-to-paste draft file
    draft_path = manual_draft.write_local(
        title, body, SITE_URL,
        platform_notes={
            "Quora": "הדבק כתשובה לשאלה רלוונטית, לא כפוסט חופשי",
            "LinkedIn": "פוסט אישי - הדבק כמו שהוא",
            "TikTok": "הפוך לתסריט קצר לוידאו 30-60 שניות",
        },
    )
    log(f"Manual draft written: {draft_path} (TikTok, Quora, LinkedIn, Flipboard, Slideshare, About.me)")

    log("=== Done ===")
    with open("run_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))


if __name__ == "__main__":
    main()
