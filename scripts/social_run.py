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
import json
from datetime import datetime
from openai import OpenAI

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta, blogger, pinterest, manual_draft
from publication_policy import (
    CTA_PROMPT,
    REPUTATION_KNOWLEDGE_PROMPT,
    enforce_channel_policy,
    enforce_publication_policy,
)

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
    "איך להעריך מידע רפואי ברשת ולזהות מקור אמין",
    "מה חשוב לשאול רופא או רופאה לפני ניתוח גינקולוגי",
]

LOG_LINES = []


def content_is_frozen():
    path = os.path.join(os.path.dirname(__file__), "..", "data", "command_center.json")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return bool(json.load(handle).get("content_freeze"))
    except (OSError, ValueError, TypeError):
        return False


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_LINES.append(line)


def generate_social_post(topic):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    prompt = f"""כתוב פוסט קצר לרשתות חברתיות (עד 120 מילים) בעברית עבור ד״ר גיא רופא,
יוצר תוכן רפואי, על הנושא: {topic}

טון: חם, מקצועי, נגיש. שורה ראשונה = הוק שמושך תשומת לב.
אל תשתמש בהאשטגים. אל תשתמש בכותרות markdown.
{CTA_PROMPT}"""
    prompt += "\n" + REPUTATION_KNOWLEDGE_PROMPT
    resp = client.chat.completions.create(
        model="gpt-4o", messages=[{"role": "user", "content": prompt}], max_tokens=400
    )
    body = resp.choices[0].message.content.strip()
    body = enforce_publication_policy(body)
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
    except meta.DuplicatePostError as e:
        log(f"{name}: {e}")
        return None
    except Exception as e:
        log(f"{name}: FAILED -> {e}")
        return None


def main():
    log("=== Dr. Rofe Social Distribution - Starting ===")

    if os.environ.get("PUBLISH_APPROVED", "").strip().lower() != "true":
        log("SAFE STOP: no explicit publication approval")
        raise SystemExit(1)

    if content_is_frozen():
        log("CONTENT FREEZE: social distribution paused by Reputation Command Center")
        log("=== Done (safely paused) ===")
        return

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
    enforce_channel_policy("Facebook")
    try_publish("Facebook", meta.facebook_is_configured, meta.publish_facebook, title, body, SITE_URL)
    log("Twitter/X: SKIPPED (disabled by product reputation strategy)")
    log("Tumblr: SKIPPED (deferred until it has a distinct audience purpose)")
    log("Telegram: SKIPPED (deferred until it has a distinct audience purpose)")
    try_publish("Blogger", blogger.is_configured, blogger.publish, title, f"<p>{body}</p>", SITE_URL)

    # Instagram is owner-managed for this pilot. The product never publishes there.
    log("Instagram: SKIPPED (owner-managed pilot channel)")

    # Pinterest needs an image and remains independently configurable.
    image_url = os.environ.get("SOCIAL_IMAGE_URL")
    if image_url:
        try_publish("Pinterest", pinterest.is_configured, pinterest.publish, title, body, SITE_URL, image_url)
    else:
        log("Pinterest: SKIPPED (no SOCIAL_IMAGE_URL set)")

    # Tier 3: no safe posting API - write a ready-to-paste draft file
    draft_path = manual_draft.write_local(
        title, body, SITE_URL,
        platform_notes={
            "Quora": "הדבק כתשובה לשאלה רלוונטית, לא כפוסט חופשי",
            "LinkedIn": "פוסט אישי - הדבק כמו שהוא",
        },
    )
    log(f"Manual draft written: {draft_path} (Quora, LinkedIn, Flipboard, Slideshare, About.me)")
    log("TikTok: SKIPPED (owner-managed pilot channel)")

    log("=== Done ===")
    with open("run_log.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LOG_LINES))


if __name__ == "__main__":
    main()
