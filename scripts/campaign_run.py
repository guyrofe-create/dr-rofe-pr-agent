#!/usr/bin/env python3
"""Publish one medically approved draft as a coordinated owned-media campaign."""

import json
import html
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))

from daily_run import load_draft, resolve_draft_path
from social_publishers import blogger, meta, pinterest, telegram, tumblr, twitter
from publication_policy import enforce_publication_policy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = PROJECT_ROOT / "content_drafts" / "campaigns"
LOG_LINES = []


def utc_now():
    return datetime.now(timezone.utc)


def log(message):
    line = f"[{utc_now():%H:%M:%S}] {message}"
    print(line)
    LOG_LINES.append(line)


def configured(*names):
    return all(os.environ.get(name, "").strip() for name in names)


def stable_slug(title):
    value = re.sub(r"[^\w\u0590-\u05FF-]+", "-", title, flags=re.UNICODE)
    return re.sub(r"-+", "-", value).strip("-").lower()[:180]


def first_paragraph(content):
    body = re.sub(r"^#.*$", "", content, count=1, flags=re.MULTILINE).strip()
    paragraph = next(
        (
            re.sub(r"\s+", " ", block).strip()
            for block in re.split(r"\n\s*\n", body)
            if block.strip() and not block.lstrip().startswith("#")
        ),
        "",
    )
    return re.sub(r"[*_`>\[\]]", "", paragraph)


def render_inline(value):
    rendered = html.escape(value)
    rendered = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2">\1</a>',
        rendered,
    )
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    return rendered


def markdown_to_html(content):
    blocks = []
    paragraph = []

    def flush_paragraph():
        if paragraph:
            blocks.append(f"<p>{render_inline(' '.join(paragraph))}</p>")
            paragraph.clear()

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            flush_paragraph()
        elif stripped.startswith("# "):
            # WordPress renders the post title separately.
            continue
        elif stripped.startswith("## "):
            flush_paragraph()
            blocks.append(f"<h2>{render_inline(stripped[3:])}</h2>")
        elif stripped.startswith("### "):
            flush_paragraph()
            blocks.append(f"<h3>{render_inline(stripped[4:])}</h3>")
        else:
            paragraph.append(stripped)
    flush_paragraph()
    return "\n".join(blocks)


def wordpress_publish(
    base_url,
    username,
    app_password,
    title,
    content_html,
    summary_only=False,
    canonical_url=None,
    idempotency_key=None,
):
    slug_suffix = "-summary" if summary_only else ""
    slug = stable_slug((idempotency_key or title) + slug_suffix)
    auth = (username, app_password)
    endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": "DrRofeCampaignPublisher/1.0 (+https://guyrofe.com)",
    }
    response = requests.get(
        endpoint,
        params={"slug": slug, "status": "publish", "_fields": "id,link,slug"},
        headers=headers,
        timeout=25,
    )
    response.raise_for_status()
    try:
        existing = response.json()
    except requests.exceptions.JSONDecodeError as exc:
        raise RuntimeError(
            f"{base_url} returned a non-JSON response to the WordPress API lookup"
        ) from exc
    if existing:
        return existing[0].get("link") or f"{base_url.rstrip('/')}/?p={existing[0]['id']}"

    payload = {
        "title": title,
        "slug": slug,
        "status": "publish",
        "content": content_html,
    }
    if canonical_url:
        payload["excerpt"] = f'לקריאה מלאה במקור: <a href="{canonical_url}">{canonical_url}</a>'
    response = requests.post(
        endpoint, auth=auth, json=payload, headers=headers, timeout=30
    )
    response.raise_for_status()
    result = response.json()
    return result.get("link") or f"{base_url.rstrip('/')}/?p={result['id']}"


def destination(name, status, url=None, detail=None):
    item = {"name": name, "status": status}
    if url:
        item["url"] = url
    if detail:
        item["detail"] = detail
    return item


def attempt(name, is_ready, publisher, *args):
    if not is_ready:
        return destination(name, "not_configured", detail="החיבור אינו מוגדר")
    try:
        return destination(name, "published", url=publisher(*args))
    except meta.DuplicatePostError as exc:
        return destination(
            name,
            "skipped_duplicate",
            url=exc.existing_url,
            detail="נמצא פרסום דומה או קישור זהה בפוסטים האחרונים",
        )
    except Exception as exc:
        return destination(name, "failed", detail=str(exc)[:300])


def write_campaign_result(draft_path, title, destinations, status="completed"):
    CAMPAIGN_ROOT.mkdir(parents=True, exist_ok=True)
    relative_draft = draft_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    result = {
        "draft": relative_draft,
        "title": title,
        "status": status,
        "published_at": utc_now().isoformat(),
        "destinations": destinations,
    }
    output = CAMPAIGN_ROOT / f"{draft_path.stem}.json"
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    index_path = CAMPAIGN_ROOT / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        index = {"campaigns": []}
    campaigns = [
        item for item in index.get("campaigns", []) if item.get("draft") != relative_draft
    ]
    campaigns.append(result)
    index["campaigns"] = sorted(
        campaigns, key=lambda item: item.get("published_at", ""), reverse=True
    )[:50]
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output


def publish_campaign(draft_path):
    title, content = load_draft(draft_path)
    enforce_publication_policy(content)
    article_html = markdown_to_html(content)
    summary = first_paragraph(content)
    destinations = []

    if not configured("WORDPRESS_GUYROFE_COM_USER", "WORDPRESS_GUYROFE_COM_API"):
        raise RuntimeError("Canonical WordPress publisher is not configured")

    canonical_url = wordpress_publish(
        "https://guyrofe.com",
        os.environ["WORDPRESS_GUYROFE_COM_USER"],
        os.environ["WORDPRESS_GUYROFE_COM_API"],
        title,
        article_html,
        idempotency_key=f"dr-rofe-{draft_path.stem}",
    )
    destinations.append(destination("guyrofe.com", "published", url=canonical_url))
    log(f"Canonical article published: {canonical_url}")

    if configured(
        "WORDPRESS_DRGUYROFE_CO_IL_USER", "WORDPRESS_DRGUYROFE_CO_IL_API"
    ):
        summary_html = (
            f"<p>{summary}</p><p><a href=\"{canonical_url}\">"
            "לקריאת המאמר המלא באתר הראשי</a></p>"
        )
        destinations.append(
            attempt(
                "drguyrofe.co.il",
                True,
                wordpress_publish,
                "https://www.drguyrofe.co.il",
                os.environ["WORDPRESS_DRGUYROFE_CO_IL_USER"],
                os.environ["WORDPRESS_DRGUYROFE_CO_IL_API"],
                title,
                summary_html,
                True,
                canonical_url,
                f"dr-rofe-{draft_path.stem}",
            )
        )
    else:
        destinations.append(
            destination("drguyrofe.co.il", "not_configured", detail="חיבור WordPress חסר")
        )

    destinations.append(
        attempt(
            "Facebook",
            meta.facebook_is_configured(),
            meta.publish_facebook,
            title,
            summary,
            canonical_url,
        )
    )
    destinations.append(
        attempt(
            "X",
            twitter.is_configured(),
            twitter.publish,
            title,
            summary,
            canonical_url,
        )
    )
    destinations.append(
        attempt(
            "Tumblr",
            tumblr.is_configured(),
            tumblr.publish,
            title,
            summary,
            canonical_url,
        )
    )
    destinations.append(
        attempt(
            "Telegram",
            telegram.is_configured(),
            telegram.publish,
            title,
            summary,
            canonical_url,
        )
    )
    destinations.append(
        attempt(
            "Blogger",
            blogger.is_configured(),
            blogger.publish,
            title,
            f"<p>{summary}</p>",
            canonical_url,
        )
    )

    image_url = os.environ.get("SOCIAL_IMAGE_URL", "").strip()
    destinations.append(
        destination(
            "Instagram",
            "owner_managed",
            detail="ערוץ הפיילוט מנוהל עצמאית; המוצר אינו מפרסם בו",
        )
    )
    destinations.append(
        attempt(
            "Pinterest",
            bool(image_url) and pinterest.is_configured(),
            pinterest.publish,
            title,
            summary,
            canonical_url,
            image_url,
        )
        if image_url
        else destination("Pinterest", "blocked", detail="נדרשת תמונה מאושרת")
    )

    destinations.extend(
        [
            destination(
                "drguyrofe.com",
                "blocked",
                detail="חיבור Wix קיים אך הרשאות הפרסום עדיין חסומות",
            ),
            destination(
                "Medium",
                "paused",
                detail="הפצה משנית הושהתה עד להגדרת קישור קנוני תקין",
            ),
            destination(
                "LinkedIn / TikTok / Quora",
                "manual_only",
                detail="אין כרגע חיבור פרסום רשמי בטוח",
            ),
        ]
    )
    return title, canonical_url, destinations


def main():
    draft_path = resolve_draft_path(os.environ.get("DRAFT_PATH"))
    log(f"Starting approved campaign: {draft_path}")
    try:
        title, canonical_url, destinations = publish_campaign(draft_path)
        write_campaign_result(draft_path, title, destinations)
        log(f"Campaign completed. Canonical URL: {canonical_url}")
    finally:
        Path("run_log.txt").write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
