#!/usr/bin/env python3
"""Generate reviewed medical drafts and publish approved drafts to Medium.

Scheduled runs generate a durable draft only. Publishing is a separate,
explicitly approved workflow-dispatch operation.
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
import time
from urllib.parse import urlparse

import requests
from reputation_core.strategy import client_content_plan, load_client_profile
from reputation_core.entity_contract import (
    apply_article_contract,
    audit_article_entity_contract,
)
from publication_policy import (
    CTA_PROMPT,
    REPUTATION_KNOWLEDGE_PROMPT,
    enforce_publication_policy,
)


CONTENT_PLAN = client_content_plan()
TOPICS = CONTENT_PLAN.get("topics", [])
TAGS = CONTENT_PLAN.get("tags", [])
MIN_ARTICLE_WORDS = 900
TARGET_ARTICLE_WORDS = "1100-1400"
MAX_ARTICLE_WORDS = 1800
LOG_LINES = []
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_PROFILE = load_client_profile()
CLIENT_FACTS = CLIENT_PROFILE["canonical_facts"]
TRUSTED_MEDICAL_SOURCE_DOMAINS = frozenset(
    {
        "who.int",
        "cdc.gov",
        "nih.gov",
        "ncbi.nlm.nih.gov",
        "medlineplus.gov",
        "fda.gov",
        "nhs.uk",
        "nice.org.uk",
        "gov.il",
        "health.gov.il",
        "acog.org",
        "rcog.org.uk",
        "figo.org",
        "asrm.org",
        "eshre.eu",
        "menopause.org",
        "ema.europa.eu",
        "ecdc.europa.eu",
        "cochranelibrary.com",
        "doi.org",
    }
)
OFFICIAL_MEDICAL_SOURCE_DOMAINS = TRUSTED_MEDICAL_SOURCE_DOMAINS - {
    "doi.org",
    "cochranelibrary.com",
}


def utc_now():
    return datetime.now(timezone.utc)


def content_is_frozen():
    path = PROJECT_ROOT / "data" / "command_center.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            return bool(json.load(handle).get("content_freeze"))
    except (OSError, ValueError, TypeError):
        return False


def log(msg):
    ts = utc_now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG_LINES.append(line)


def write_run_log(path=None):
    output = Path(path or os.environ.get("RUN_LOG_PATH", "run_log.txt"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")
    return output


def draft_root():
    return Path(os.environ.get("CONTENT_DRAFT_DIR", "content_drafts"))


def selected_topic(now=None):
    if not TOPICS:
        raise RuntimeError("installation has no approved content topics")
    now = now or utc_now()
    week = now.isocalendar()[1]
    day = now.weekday()
    start = (week * 3 + day) % len(TOPICS)
    index_path = draft_root() / "index.json"
    try:
        history = json.loads(index_path.read_text(encoding="utf-8")).get(
            "drafts", []
        )
    except (OSError, ValueError, TypeError):
        history = []

    last_seen = {}
    for item in history:
        topic = item.get("topic")
        generated_at = item.get("generated_at", "")
        if topic in TOPICS and generated_at > last_seen.get(topic, ""):
            last_seen[topic] = generated_at

    ordered_indexes = [
        (start + offset) % len(TOPICS) for offset in range(len(TOPICS))
    ]
    never_used = [
        index for index in ordered_indexes if TOPICS[index] not in last_seen
    ]
    if never_used:
        index = never_used[0]
    else:
        index = min(
            ordered_indexes,
            key=lambda candidate: (
                last_seen[TOPICS[candidate]],
                ordered_indexes.index(candidate),
            ),
        )
    return index, TOPICS[index]


def clean_generated_markdown(content):
    content = (content or "").strip()
    fenced = re.fullmatch(
        r"```(?:markdown|md)?\s*\n?(.*?)\n?```\s*",
        content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        content = fenced.group(1).strip()
    return content


def _source_domain(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _domain_is_allowed(domain, allowed):
    return any(domain == item or domain.endswith(f".{item}") for item in allowed)


def medical_source_urls(content):
    match = re.search(
        r"^#{2,3}\s+מקורות\b(?P<section>.*)\Z",
        content,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return set()
    return {
        url.rstrip(".,;)")
        for url in re.findall(r"https?://[^\s>)\]]+", match.group("section"))
    }


def validate_generated_article(content):
    enforce_publication_policy(content)
    title = next(
        (
            line.removeprefix("#").strip()
            for line in content.splitlines()
            if re.match(r"^#\s+\S", line)
        ),
        "",
    )
    if not title:
        raise ValueError("generated article is missing an H1 title")
    plain_text = re.sub(r"https?://\S+", " ", content)
    plain_text = re.sub(r"[#*_`>\[\]()]+", " ", plain_text)
    word_count = len(re.findall(r"\S+", plain_text))
    if not MIN_ARTICLE_WORDS <= word_count <= MAX_ARTICLE_WORDS:
        raise ValueError(
            f"generated article has {word_count} words; "
            f"expected {MIN_ARTICLE_WORDS}-{MAX_ARTICLE_WORDS}"
        )
    if CONTENT_PLAN.get("medical_content") and not re.search(
        r"^#{2,3}\s+מקורות\b", content, flags=re.MULTILINE
    ):
        raise ValueError("generated medical article is missing a Sources section")
    all_urls = {
        url.rstrip(".,;)")
        for url in re.findall(r"https?://[^\s>)\]]+", content)
    }
    if CONTENT_PLAN.get("medical_content"):
        source_urls = medical_source_urls(content)
        if len(source_urls) < 2:
            raise ValueError(
                "generated medical article needs at least 2 direct source URLs"
            )
        untrusted = sorted(
            url
            for url in all_urls
            if _source_domain(url)
            != _source_domain(CLIENT_FACTS["canonical_site"])
            if not _domain_is_allowed(
                _source_domain(url), TRUSTED_MEDICAL_SOURCE_DOMAINS
            )
        )
        if untrusted:
            raise ValueError(
                "generated medical article contains a non-approved medical "
                f"source domain: {untrusted[0]}"
            )
        official_count = sum(
            _domain_is_allowed(
                _source_domain(url), OFFICIAL_MEDICAL_SOURCE_DOMAINS
            )
            for url in source_urls
        )
        if official_count < 2:
            raise ValueError(
                "generated medical article needs at least 2 official "
                "institutional medical sources"
            )
    entity_report = audit_article_entity_contract(content, CLIENT_PROFILE)
    if not entity_report.passed:
        raise ValueError(
            "generated article failed entity contract: "
            + "; ".join(entity_report.errors)
        )
    return title, word_count


def generation_messages(base_prompt, previous_content=None, last_error=None):
    messages = [{"role": "user", "content": base_prompt}]
    if previous_content:
        messages.extend(
            [
                {"role": "assistant", "content": previous_content},
                {
                    "role": "user",
                    "content": (
                        "הטיוטה הזו לא עברה בקרת איכות: "
                        f"{last_error}. הרחב ושפר את אותה טיוטה עד "
                        f"{TARGET_ARTICLE_WORDS} "
                        "מילים. שמור על הכותרת, המבנה והמידע הקיים, הוסף "
                        "הסברים שימושיים שאינם חוזרים על עצמם, ואל תתחיל "
                        "מאמר חדש. החזר רק את המאמר המורחב."
                    ),
                },
            ]
        )
    elif last_error:
        messages[0]["content"] += (
            "\n\nהניסיון הקודם נכשל: "
            f"{last_error}. ודא שהתשובה מלאה ועומדת בכל הדרישות."
        )
    return messages


def generate_article(topic):
    from openai import OpenAI

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    content_kind = "מאמר רפואי מקצועי" if CONTENT_PLAN.get("medical_content") else "מאמר מקצועי"
    medical_rules = (
        "- כל טענה רפואית מחייבת בדיקת רופא לפני פרסום\n"
        '- הוסף בסוף סעיף "מקורות" ובו לפחות שני קישורים ישירים למקורות '
        "רפואיים מוסדיים רשמיים שעליהם מבוסס המאמר\n"
        "- מקורות מותרים בלבד: WHO, רשויות בריאות ממשלתיות, NIH/NCBI, "
        "CDC, FDA, NHS/NICE, משרד הבריאות הישראלי, EMA/ECDC, ACOG, "
        "RCOG, FIGO, ASRM, ESHRE, The Menopause Society, Cochrane "
        "ומאמרים מדעיים דרך DOI\n"
        "- אסור להשתמש כבסיס רפואי באתרי חדשות, בלוגים, רשתות חברתיות, "
        "אתרי מרפאות מסחריות, אתרי תוכן שיווקי או מקור שאינו ברשימה "
        "המאושרת"
        if CONTENT_PLAN.get("medical_content")
        else "- כל טענה מהותית מחייבת מקור סמכותי וביקורת אנושית לפני פרסום"
    )
    base_prompt = f"""כתוב טיוטת {content_kind} בשפת {CONTENT_PLAN.get('language', 'he')} עבור {CLIENT_FACTS['primary_name']}.
התפקיד הנוכחי המאושר: {CLIENT_FACTS['current_role']}.

נושא: {topic}

דרישות:
- אורך יעד: {TARGET_ARTICLE_WORDS} מילים; לעולם לא פחות
  מ-{MIN_ARTICLE_WORDS} מילים, ובלי מלל מנופח או חזרות מלאכותיות
- שפה: עברית מקצועית אך נגישה לקהל רחב
- מבנה: כותרת ראשית H1, מבוא, 4-6 סעיפים עם כותרות H2, סיכום
- הכותרת תסתיים פעם אחת בלבד ב-"| {CLIENT_FACTS['primary_name']}"
- מיד לאחר הכותרת תופיע שורת מחבר מקושרת לפרופיל הרשמי
- לפני המקורות תופיע תיבת "על המחבר" עם התפקיד והסטטוס הנוכחיים המאושרים
- אין לחזור על שם הלקוח באופן מלאכותי בגוף המאמר
- פתח בתשובה ישירה וקצרה לשאלה המרכזית ורק לאחר מכן הרחב
- השתמש בטבלה רק כאשר היא משפרת השוואה אמיתית; אין להוסיף טבלה לקישוט
- הוסף FAQ רק אם קיימות שאלות שימושיות שלא נענו היטב בגוף המאמר
- העדף מקורות ראשוניים ורשמיים, והפרד בבירור בין עובדות לבין ניתוח מקורי
- {CTA_PROMPT}
- {REPUTATION_KNOWLEDGE_PROMPT}
- אין להמציא נתונים, שיעורי הצלחה, תארים או ניסיון אישי
- אין להציג את הלקוח באופן שסותר את הסטטוס המאושר:
  {CLIENT_FACTS['public_status_he']}
- אין להזמין לייעוץ, ליצירת קשר או לקביעת תור
- אין לייחס ל{CLIENT_FACTS['primary_name']} אמירות, הדגשות או המלצות אישיות שלא סופקו
{medical_rules}
- פורמט: Markdown
- אין לעטוף את התשובה בבלוק קוד ואין לכתוב את המילה markdown

החזר רק את הטיוטה."""
    last_error = None
    previous_content = None
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        content = request_generated_article(
            client,
            generation_messages(
                base_prompt,
                previous_content=previous_content,
                last_error=last_error,
            ),
        )
        content = apply_article_contract(
            clean_generated_markdown(content),
            CLIENT_PROFILE,
        )
        if not content:
            last_error = "הוחזרה תשובה ריקה"
            continue
        previous_content = content
        try:
            title, word_count = validate_generated_article(content)
            log(f"Draft quality passed: {word_count} words")
            return title, content
        except ValueError as exc:
            last_error = str(exc)
            log(
                f"Draft quality attempt {attempt}/{max_attempts} "
                f"failed: {last_error}"
            )

    raise RuntimeError(f"OpenAI draft failed quality checks: {last_error}")


def request_generated_article(client, messages):
    response = client.responses.create(
        model=os.environ.get("OPENAI_CONTENT_MODEL", "gpt-5.6"),
        input=messages,
        reasoning={"effort": "low"},
        text={"verbosity": "high"},
        max_output_tokens=4500,
    )
    return response.output_text or ""


def draft_run_suffix(now):
    """Return a collision-resistant suffix for one explicit generation run."""
    github_run_id = re.sub(r"[^A-Za-z0-9_-]", "", os.environ.get("GITHUB_RUN_ID", ""))
    github_run_attempt = re.sub(
        r"[^A-Za-z0-9_-]", "", os.environ.get("GITHUB_RUN_ATTEMPT", "")
    )
    if github_run_id:
        return (
            f"run-{github_run_id}-attempt-{github_run_attempt}"
            if github_run_attempt
            else f"run-{github_run_id}"
        )
    return now.strftime("%H%M%S-%f")


def save_draft(topic_index, topic, title, content, now=None):
    now = now or utc_now()
    root = draft_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / (
        f"{now:%Y-%m-%d}-topic-{topic_index:02d}-{draft_run_suffix(now)}.md"
    )
    metadata = (
        "<!--\n"
        "status: pending_medical_review\n"
        f"generated_at: {now.isoformat()}\n"
        f"topic: {topic}\n"
        "-->\n\n"
    )
    body = content if re.search(r"^#\s+", content, flags=re.MULTILINE) else f"# {title}\n\n{content}"
    path.write_text(metadata + body.rstrip() + "\n", encoding="utf-8")
    update_draft_index(path, topic, title, content, now)
    return path


def update_draft_index(path, topic, title, content, generated_at):
    index_path = draft_root() / "index.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {"drafts": []}
    relative_path = path.as_posix()
    if not path.is_absolute():
        relative_path = path.as_posix()
    excerpt = re.sub(r"[#*_`>-]", "", content)
    excerpt = " ".join(excerpt.split())[:240]
    item = {
        "path": relative_path,
        "title": title,
        "topic": topic,
        "excerpt": excerpt,
        "generated_at": generated_at.isoformat(),
    }
    drafts = [
        existing
        for existing in payload.get("drafts", [])
        if existing.get("path") != relative_path
    ]
    drafts.append(item)
    payload["drafts"] = sorted(
        drafts, key=lambda value: value.get("generated_at", ""), reverse=True
    )[:30]
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def resolve_draft_path(value):
    if not value:
        raise ValueError("DRAFT_PATH is required in publish mode")
    root = draft_root().resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("DRAFT_PATH must be inside the content draft directory")
    if candidate.suffix.lower() != ".md" or not candidate.is_file():
        raise ValueError(f"Draft does not exist: {candidate}")
    return candidate


def load_draft(path):
    content = path.read_text(encoding="utf-8")
    content = re.sub(r"\A<!--.*?-->\s*", "", content, flags=re.DOTALL)
    title = next(
        (line.lstrip("#").strip() for line in content.splitlines() if line.startswith("#")),
        "",
    )
    if not title or not content.strip():
        raise ValueError(f"Draft is missing a Markdown title or body: {path}")
    return title, content.strip()


def record_publication(draft_path, url):
    draft_path = draft_path.resolve()
    try:
        draft_value = draft_path.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(
            "Published draft must be inside the project directory"
        ) from exc

    published_dir = draft_root() / "published"
    published_dir.mkdir(parents=True, exist_ok=True)
    output = published_dir / f"{draft_path.stem}.json"
    output.write_text(
        json.dumps(
            {
                "draft": draft_value,
                "published_at": utc_now().isoformat(),
                "url": url,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    index_path = draft_root() / "publications.json"
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        payload = {"publications": []}
    item = {
        "draft": draft_value,
        "published_at": utc_now().isoformat(),
        "url": url,
    }
    publications = [
        existing
        for existing in payload.get("publications", [])
        if existing.get("draft") != draft_value
    ]
    publications.append(item)
    payload["publications"] = publications
    index_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def publish_via_api(token, title, content):
    log("Using Method A: legacy Medium API token")
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
        },
        timeout=30,
    )
    resp.raise_for_status()
    url = (resp.json().get("data") or {}).get("url")
    if not url or not url.startswith("https://medium.com/"):
        raise RuntimeError("Medium API did not return a published story URL")
    return url


def goto_with_retry(page, url, attempts=2):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            # Medium is a long-lived SPA. networkidle never becomes reliable.
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1_500)
            return
        except Exception as exc:
            last_error = exc
            log(f"Navigation attempt {attempt}/{attempts} failed: {exc}")
            if attempt < attempts:
                page.wait_for_timeout(2_000)
    raise last_error


def save_medium_debug(page):
    try:
        Path("medium_debug.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path="medium_debug.png", full_page=True)
        log("Saved medium_debug.html and medium_debug.png")
    except Exception as exc:
        log(f"Could not save Medium diagnostics: {exc}")


def publish_via_cookie(sid, title, content_md):
    log("Using Method B: Medium session cookie")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )
        )
        context.add_cookies(
            [
                {
                    "name": "sid",
                    "value": sid,
                    "domain": ".medium.com",
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                }
            ]
        )
        page = context.new_page()
        page.set_default_timeout(30_000)

        try:
            log("Verifying Medium session...")
            goto_with_retry(page, "https://medium.com/me/stories/drafts")
            if any(part in page.url.lower() for part in ("signin", "login", "m/signin")):
                raise RuntimeError("Medium session expired; refresh the MEDIUM_SID secret")

            log("Opening Medium editor...")
            goto_with_retry(page, "https://medium.com/new-story")

            title_el = page.locator('h1[data-placeholder="Title"]').first
            title_el.wait_for(state="visible", timeout=30_000)
            log("Typing title and approved body...")
            title_el.click()
            title_el.fill(title)
            page.keyboard.press("Enter")

            plain = content_md
            for symbol in ("### ", "## ", "# ", "**", "__"):
                plain = plain.replace(symbol, "")
            page.keyboard.type(plain, delay=1)

            log("Publishing approved Medium draft...")
            first_publish = page.locator("button:has-text('Publish')").first
            first_publish.wait_for(state="visible", timeout=20_000)
            first_publish.click()
            confirm = page.locator("button:has-text('Publish now')").first
            confirm.wait_for(state="visible", timeout=20_000)
            editor_url = page.url
            confirm.click()
            page.wait_for_timeout(5_000)

            url = page.url
            if url == editor_url or "new-story" in url or url.endswith("/edit"):
                raise RuntimeError("Medium did not confirm publication with a story URL")
            if not url.startswith("https://medium.com/"):
                raise RuntimeError(f"Unexpected Medium result URL: {url}")
            log(f"Medium confirmed publication: {url}")
            return url
        except Exception:
            save_medium_debug(page)
            raise
        finally:
            browser.close()


def generate_mode():
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY secret is not set")
    index, topic = selected_topic()
    log(f"Topic: {topic}")
    log("Generating medical draft via OpenAI...")
    title, content = generate_article(topic)
    path = save_draft(index, topic, title, content)
    generated_path_file = os.environ.get("GENERATED_DRAFT_PATH_FILE")
    if generated_path_file:
        output = Path(generated_path_file)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(path.as_posix() + "\n", encoding="utf-8")
    log(f"Draft saved for medical review: {path}")
    log("No content was published")


def publish_mode():
    path = resolve_draft_path(os.environ.get("DRAFT_PATH"))
    title, content = load_draft(path)
    enforce_publication_policy(content)
    medium_token = os.environ.get("MEDIUM_TOKEN")
    medium_sid = os.environ.get("MEDIUM_SID")
    if not medium_token and not medium_sid:
        raise RuntimeError("Set either MEDIUM_TOKEN or MEDIUM_SID in GitHub Secrets")
    log(f"Publishing approved draft: {path}")
    if medium_token:
        url = publish_via_api(medium_token, title, content)
    else:
        url = publish_via_cookie(medium_sid, title, content)
    result_path = record_publication(path, url)
    log(f"Publication recorded: {result_path}")


def main():
    LOG_LINES.clear()
    log(f"=== {CLIENT_PROFILE['display_name']} Content Workflow - Starting ===")
    log(f"Date: {utc_now():%Y-%m-%d %H:%M UTC}")

    if content_is_frozen():
        log("CONTENT FREEZE: generation and publication paused")
        return

    mode = os.environ.get("RUN_MODE", "generate").strip().lower()
    if mode == "generate":
        generate_mode()
    elif mode == "publish":
        publish_mode()
    else:
        raise ValueError(f"Unsupported RUN_MODE: {mode}")
    log("=== Done ===")


if __name__ == "__main__":
    exit_code = 0
    try:
        main()
    except Exception as exc:
        log(f"ERROR: {type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        write_run_log()
    raise SystemExit(exit_code)
