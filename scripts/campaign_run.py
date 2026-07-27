#!/usr/bin/env python3
"""Publish one medically approved draft as a coordinated owned-media campaign."""

import json
import html
import hashlib
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(__file__))

from daily_run import load_draft, resolve_draft_path
from social_publishers import (
    blogger,
    linkedin,
    meta,
    pinterest,
)
from publication_policy import enforce_channel_policy, enforce_publication_policy
import social_image
from reputation_core import data_path, load_client_profile
from reputation_core.approval_workflow import (
    ExecutionLedger,
    ReconciliationRequired,
    verify_approval,
)
from reputation_core.entity_seo import (
    build_article_schema,
    extract_citation_urls,
    json_ld_script,
)
from reputation_core.platform_content import build_platform_variants


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = PROJECT_ROOT / "content_drafts" / "campaigns"
EXECUTION_LEDGER_PATH = PROJECT_ROOT / "publication_receipts" / "execution_ledger.json"
LOG_LINES = []
CLIENT_PROFILE = load_client_profile()


def load_business_profile():
    return json.loads(data_path("business_profile.json").read_text(encoding="utf-8"))


def canonical_site(profile):
    return next(
        (site for site in profile["sites"] if site.get("canonical")),
        profile["sites"][0],
    )


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
    article_schema_factory=None,
):
    slug_suffix = "-summary" if summary_only else ""
    slug = stable_slug((idempotency_key or title) + slug_suffix)
    auth = (username, app_password)
    endpoint = f"{base_url.rstrip('/')}/wp-json/wp/v2/posts"
    headers = {
        "Accept": "application/json",
        "Cache-Control": "no-cache",
        "User-Agent": (
            f"ReputationAgent/{CLIENT_PROFILE['client_id']} "
            f"(+{CLIENT_PROFILE['canonical_facts']['canonical_site']})"
        ),
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
        link = existing[0].get("link") or f"{base_url.rstrip('/')}/?p={existing[0]['id']}"
        if article_schema_factory:
            schema = article_schema_factory(link)
            requests.post(
                f"{endpoint}/{existing[0]['id']}",
                auth=auth,
                json={"content": content_html + "\n" + json_ld_script(schema)},
                headers=headers,
                timeout=30,
            ).raise_for_status()
        return link

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
    link = result.get("link") or f"{base_url.rstrip('/')}/?p={result['id']}"
    if article_schema_factory:
        schema = article_schema_factory(link)
        requests.post(
            f"{endpoint}/{result['id']}",
            auth=auth,
            json={"content": content_html + "\n" + json_ld_script(schema)},
            headers=headers,
            timeout=30,
        ).raise_for_status()
    return link


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


def write_campaign_result(
    draft_path,
    title,
    destinations,
    status="completed",
    approval_id_value=None,
):
    CAMPAIGN_ROOT.mkdir(parents=True, exist_ok=True)
    relative_draft = draft_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    result = {
        "draft": relative_draft,
        "title": title,
        "status": status,
        "published_at": utc_now().isoformat(),
        "destinations": destinations,
        "approval_id": approval_id_value,
        "execution_receipt_ledger": (
            EXECUTION_LEDGER_PATH.relative_to(PROJECT_ROOT).as_posix()
        ),
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


def _target_map(bundle):
    return {item["target_id"]: item for item in bundle["targets"]}


def _execute_target(ledger, bundle, target, publisher):
    receipt = ledger.execute(bundle, target, publisher)
    return destination(
        target["platform"],
        "published",
        url=receipt["url"],
        detail=f"idempotency_key={receipt['idempotency_key']}",
    )


def _execute_target_safely(ledger, bundle, target, publisher):
    """Execute one approved destination without hiding other destination results."""
    try:
        return _execute_target(ledger, bundle, target, publisher)
    except Exception as exc:
        log(f"{target['platform']} publication failed: {exc}")
        return destination(
            target["platform"],
            "failed",
            detail=str(exc)[:300],
        )


def _load_verified_approval():
    bundle_path = os.environ.get("APPROVAL_BUNDLE_PATH", "").strip()
    record_path = os.environ.get("APPROVAL_RECORD_PATH", "").strip()
    secret = os.environ.get("APPROVAL_SIGNING_SECRET", "")
    if not bundle_path or not record_path or not secret:
        raise RuntimeError(
            "APPROVAL_BUNDLE_PATH, APPROVAL_RECORD_PATH and "
            "APPROVAL_SIGNING_SECRET are required"
        )
    bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
    record = json.loads(Path(record_path).read_text(encoding="utf-8"))
    verify_approval(bundle, record, secret)
    return bundle, record


def _verify_source_draft(draft_path, bundle):
    expected_path = bundle.get("source_draft")
    try:
        actual_path = draft_path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        actual_path = str(draft_path.resolve())
    if expected_path != actual_path:
        raise PermissionError("Approved bundle does not match the selected draft path")
    digest = hashlib.sha256(draft_path.read_bytes()).hexdigest()
    if digest != bundle.get("source_draft_sha256"):
        raise PermissionError("Draft changed after approval")


def publish_campaign(draft_path, approved_bundle=None, ledger=None):
    if approved_bundle is None:
        raise PermissionError("A verified P7 approval bundle is required")
    _verify_source_draft(draft_path, approved_bundle)
    targets = _target_map(approved_bundle)
    ledger = ledger or ExecutionLedger(EXECUTION_LEDGER_PATH)
    title, content = load_draft(draft_path)
    enforce_publication_policy(content)
    article_html = markdown_to_html(content)
    summary = first_paragraph(content)
    destinations = []
    business = load_business_profile()
    primary = canonical_site(business)
    canonical_base = primary["base_url"].rstrip("/")
    canonical_name = re.sub(r"^www\.", "", urlparse(canonical_base).netloc)
    primary_user_env = primary["user_env"]
    primary_password_env = primary["app_password_env"]

    if not configured(primary_user_env, primary_password_env):
        raise RuntimeError("Canonical WordPress publisher is not configured")

    canonical_target = targets["canonical_wordpress"]
    canonical_payload = canonical_target["payload"]
    if canonical_payload["title"] != title or canonical_payload["markdown"] != content:
        raise PermissionError("Canonical content differs from the approved payload")
    canonical_receipt = ledger.execute(
        approved_bundle,
        canonical_target,
        lambda payload, key: {
            "url": wordpress_publish(
                canonical_base,
                os.environ[primary_user_env],
                os.environ[primary_password_env],
                payload["title"],
                markdown_to_html(payload["markdown"]),
                idempotency_key=payload["slug"],
                article_schema_factory=lambda article_url: build_article_schema(
                    business,
                    headline=payload["title"],
                    article_url=article_url,
                    description=summary,
                    citations=extract_citation_urls(payload["markdown"]),
                ),
            )
        },
    )
    canonical_url = canonical_receipt["url"]
    if canonical_url.rstrip("/") != canonical_payload["canonical_url"].rstrip("/"):
        raise ReconciliationRequired(
            "Canonical provider URL differs from the approved URL; reconcile before distribution"
        )
    destinations.append(
        destination(
            canonical_name,
            "published",
            url=canonical_url,
            detail=f"idempotency_key={canonical_receipt['idempotency_key']}",
        )
    )
    log(f"Canonical article published: {canonical_url}")

    media = approved_bundle.get("media") or {}
    image_url = str(media.get("uri") or "").strip()
    generated_image = None
    if image_url and not image_url.startswith(("http://", "https://")):
        image_path = Path(image_url)
        if not image_path.is_absolute():
            image_path = PROJECT_ROOT / image_path
        digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if not media.get("sha256") or digest != media["sha256"]:
            raise PermissionError("Approved image bytes do not match the bundle")
        generated_image = social_image.SocialImage(
            image_path.read_bytes(),
            media_type=(
                "image/png"
                if image_path.suffix.lower() == ".png"
                else "image/jpeg"
            ),
            extension=image_path.suffix.lstrip(".") or "png",
            visual_description=media.get("visual_description", ""),
            source_page_url=media.get("source_page_url", ""),
            source_image_url=media.get("source_image_url", ""),
            creator=media.get("creator", ""),
            license_name=media.get("license_name", ""),
            license_url=media.get("license_url", ""),
            attribution=media.get("attribution", ""),
            source_type=media.get(
                "source_type", "wikimedia_commons_licensed_photo"
            ),
        )
        try:
            image_url = social_image.upload_to_wordpress(
                generated_image,
                base_url=canonical_base,
                username=os.environ[primary_user_env],
                app_password=os.environ[primary_password_env],
                slug=f"{CLIENT_PROFILE['client_id']}-{draft_path.stem}-social",
                title=title,
            )
            destinations.append(
                destination(
                    "Licensed editorial photo",
                    "hosted",
                    url=image_url,
                    detail=(
                        generated_image.attribution
                        or "Real licensed photo with recorded provenance"
                    ),
                )
            )
            log(f"Pre-approved visual hosted: {image_url}")
        except Exception as exc:
            raise RuntimeError(f"Approved image upload failed: {exc}") from exc
    elif image_url:
        destinations.append(
            destination("Approved visual", "approved_remote", url=image_url)
        )
    else:
        destinations.append(
            destination(
                "Approved visual",
                "not_configured",
                detail="לא צורפה תמונה לחבילת האישור",
            )
        )

    # Secondary WordPress publication is blocked unless it is part of the exact
    # approval bundle. P7 deliberately removes implicit fan-out.
    for site in business["sites"]:
        if site is primary or site.get("platform", "wordpress") != "wordpress":
            continue
        name = re.sub(r"^www\.", "", urlparse(site["base_url"]).netloc)
        destinations.append(
            destination(name, "not_in_approval_bundle", detail="לא אושר בחבילה זו")
        )

    enforce_channel_policy("Facebook")
    facebook_target = targets["facebook_page"]
    if meta.facebook_is_configured():
        destinations.append(
            _execute_target_safely(
                ledger,
                approved_bundle,
                facebook_target,
                lambda payload, key: {
                    "url": meta.publish_facebook(
                        payload["title"],
                        payload["text"],
                        canonical_url,
                        image_url,
                        (payload.get("image") or {}).get("alt_text"),
                    )
                },
            )
        )
    else:
        destinations.append(destination("Facebook", "not_configured"))
    linkedin_target = targets["linkedin_member"]
    if linkedin.is_configured():
        destinations.append(
            _execute_target_safely(
                ledger,
                approved_bundle,
                linkedin_target,
                lambda payload, key: {
                    "url": linkedin.publish(
                        payload["title"],
                        payload["text"],
                        canonical_url,
                        generated_image.content if generated_image else None,
                        (payload.get("image") or {}).get("alt_text"),
                    )
                },
            )
        )
    else:
        destinations.append(destination("LinkedIn", "not_configured"))
    destinations.append(
        destination("X", "disabled", detail="מושבת במדיניות המוצר")
    )
    destinations.append(
        destination(
            "Tumblr",
            "deferred",
            detail="לא יופעל ללא קהל או שימוש ייחודי",
        )
    )
    destinations.append(
        destination(
            "Telegram",
            "deferred",
            detail="לא יופעל ללא קהל או שימוש ייחודי",
        )
    )
    blogger_target = targets["blogger_blog"]
    if blogger.is_configured():
        destinations.append(
            _execute_target_safely(
                ledger,
                approved_bundle,
                blogger_target,
                lambda payload, key: {
                    "url": blogger.publish(
                        payload["title"],
                        payload["html"],
                        canonical_url,
                        image_url,
                        (payload.get("image") or {}).get("alt_text"),
                    )
                },
            )
        )
    else:
        destinations.append(destination("Blogger", "not_configured"))

    destinations.append(
        destination(
            "Instagram",
            "owner_managed",
            detail="ערוץ הפיילוט מנוהל עצמאית; המוצר אינו מפרסם בו",
        )
    )
    pinterest_target = targets["pinterest_board"]
    if image_url and pinterest.is_configured():
        destinations.append(
            _execute_target_safely(
                ledger,
                approved_bundle,
                pinterest_target,
                lambda payload, key: {
                    "url": pinterest.publish(
                        payload["title"],
                        payload["description"],
                        canonical_url,
                        image_url,
                        (payload.get("image") or {}).get("alt_text"),
                    )
                },
            )
        )
    else:
        destinations.append(
            destination(
                "Pinterest",
                "blocked" if not image_url else "not_configured",
                detail="נדרשת תמונה מאושרת" if not image_url else None,
            )
        )

    for site in business["sites"]:
        if site.get("platform") == "wix":
            destinations.append(destination(
                re.sub(r"^www\.", "", urlparse(site["base_url"]).netloc),
                "blocked",
                detail="חיבור Wix קיים אך הרשאות הפרסום עדיין חסומות",
            ))
    destinations.extend(
        [
            destination(
                "Medium",
                "paused",
                detail="הפצה משנית הושהתה עד להגדרת קישור קנוני תקין",
            ),
            destination(
                "Quora",
                "manual_only",
                detail="אין כרגע חיבור פרסום רשמי בטוח",
            ),
            destination(
                "TikTok",
                "owner_managed",
                detail="ערוץ הפיילוט מנוהל עצמאית; המוצר אינו מפרסם או מכין עבורו עבודת פרסום",
            ),
        ]
    )
    return title, canonical_url, destinations


def main():
    bundle, _record = _load_verified_approval()
    draft_path = resolve_draft_path(
        os.environ.get("DRAFT_PATH") or bundle.get("source_draft")
    )
    log(f"Starting approved campaign: {draft_path}")
    try:
        try:
            title, canonical_url, destinations = publish_campaign(
                draft_path,
                approved_bundle=bundle,
            )
        except Exception as exc:
            title, _content = load_draft(draft_path)
            write_campaign_result(
                draft_path,
                title,
                [destination("Campaign", "failed", detail=str(exc)[:300])],
                status="failed",
                approval_id_value=bundle["approval_id"],
            )
            log(f"Campaign failed before distribution completed: {exc}")
            raise
        status = (
            "completed_with_errors"
            if any(item["status"] == "failed" for item in destinations)
            else "completed"
        )
        write_campaign_result(
            draft_path,
            title,
            destinations,
            status=status,
            approval_id_value=bundle["approval_id"],
        )
        log(f"Campaign {status}. Canonical URL: {canonical_url}")
    finally:
        Path("run_log.txt").write_text("\n".join(LOG_LINES) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
