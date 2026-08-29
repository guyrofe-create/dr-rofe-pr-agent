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
    google_business,
    google_oauth,
    linkedin,
    meta,
    pinterest,
)
from publication_policy import enforce_channel_policy, enforce_publication_policy
import social_image
import wix_blog
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
from reputation_core.entity_contract import meta_description
from reputation_core.platform_content import build_platform_variants


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = PROJECT_ROOT / "content_drafts" / "campaigns"
EXECUTION_LEDGER_PATH = PROJECT_ROOT / "publication_receipts" / "execution_ledger.json"
LOG_LINES = []
CLIENT_PROFILE = load_client_profile()


class CampaignTargetError(RuntimeError):
    """A named campaign destination failed before downstream distribution."""

    def __init__(self, destination_name, detail):
        super().__init__(detail)
        self.destination_name = destination_name


def load_business_profile():
    return json.loads(data_path("business_profile.json").read_text(encoding="utf-8"))


def canonical_site(profile):
    return next(
        (site for site in profile["sites"] if site.get("canonical")),
        profile["sites"][0],
    )


def site_by_key(profile, site_key):
    return next(
        (site for site in profile["sites"] if site.get("key") == site_key),
        None,
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


def public_slug(title):
    """Build a readable public slug without internal run/file identifiers."""
    value = re.sub(
        r"\s*[|｜]\s*(?:ד[\"״]ר\s+גיא\s+רופא|dr\.?\s+guy\s+rofe)\s*$",
        "",
        title or "",
        flags=re.IGNORECASE,
    ).strip()
    return stable_slug(value or title)


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
    author_section_open = False

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
            if author_section_open:
                blocks.append("</section>")
                author_section_open = False
            heading = stripped[3:]
            if heading == "על המחבר":
                blocks.append(
                    '<section class="author-disclosure" '
                    'style="font-size:0.9em;color:#59636e">'
                )
                blocks.append(
                    f'<h2 style="font-size:1em">{render_inline(heading)}</h2>'
                )
                author_section_open = True
            else:
                blocks.append(f"<h2>{render_inline(heading)}</h2>")
        elif stripped.startswith("### "):
            flush_paragraph()
            blocks.append(f"<h3>{render_inline(stripped[4:])}</h3>")
        else:
            paragraph.append(stripped)
    flush_paragraph()
    if author_section_open:
        blocks.append("</section>")
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
    meta_description=None,
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
                json={
                    "content": content_html + "\n" + json_ld_script(schema),
                    "excerpt": meta_description or "",
                },
                headers=headers,
                timeout=30,
            ).raise_for_status()
        return link

    payload = {
        "title": title,
        "slug": slug,
        "status": "publish",
        "content": content_html,
        "excerpt": meta_description or "",
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


def destination(name, status, url=None, detail=None, target_id=None):
    item = {"name": name, "status": status}
    if target_id:
        item["target_id"] = target_id
    if url:
        item["url"] = url
    if detail:
        item["detail"] = detail
    return item


def exception_detail(exc, limit=300):
    """Keep the exception class so values such as KeyError(0) stay actionable."""
    return f"{type(exc).__name__}: {exc}"[:limit]


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
        return destination(name, "failed", detail=exception_detail(exc))


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


def _execute_target(ledger, bundle, target, publisher, reconciler=None):
    receipt = ledger.execute(
        bundle, target, publisher, reconciler=reconciler
    )
    return destination(
        target["platform"],
        "published",
        url=receipt["url"],
        detail=f"idempotency_key={receipt['idempotency_key']}",
        target_id=target["target_id"],
    )


def _execute_target_safely(
    ledger, bundle, target, publisher, reconciler=None
):
    """Execute one approved destination without hiding other destination results."""
    try:
        return _execute_target(
            ledger, bundle, target, publisher, reconciler=reconciler
        )
    except Exception as exc:
        log(f"{target['platform']} publication failed: {exc}")
        return destination(
            target["platform"],
            "failed",
            detail=exception_detail(exc),
            target_id=target["target_id"],
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


def _load_approved_local_image(media):
    image_uri = str((media or {}).get("uri") or "").strip()
    if not image_uri:
        raise PermissionError("Approved target payload has no image")
    if image_uri.startswith("embedded://"):
        embedded_path = os.environ.get("APPROVED_MEDIA_PATH", "").strip()
        if not embedded_path:
            raise PermissionError("Approved embedded image bytes are unavailable")
        image_path = Path(embedded_path)
        image_bytes = image_path.read_bytes()
        digest = hashlib.sha256(image_bytes).hexdigest()
        expected_uri = f"embedded://{digest}"
        if (
            not media.get("sha256")
            or digest != media["sha256"]
            or image_uri != expected_uri
        ):
            raise PermissionError(
                "Approved embedded image bytes do not match the signed payload"
            )
        image = social_image.SocialImage(
            image_bytes,
            media_type=(
                "image/png"
                if image_path.suffix.lower() == ".png"
                else "image/webp"
                if image_path.suffix.lower() == ".webp"
                else "image/jpeg"
            ),
            extension=image_path.suffix.lstrip(".") or "jpg",
            visual_description=media.get("visual_description", ""),
            source_page_url=media.get("source_page_url", ""),
            source_image_url=media.get("source_image_url", ""),
            creator=media.get("creator", ""),
            license_name=media.get("license_name", ""),
            license_url=media.get("license_url", ""),
            attribution=media.get("attribution", ""),
            source_type=media.get("source_type", "owner_manual_upload"),
        )
        return image, ""
    if image_uri.startswith(("http://", "https://")):
        return None, image_uri
    image_path = Path(image_uri)
    if not image_path.is_absolute():
        image_path = PROJECT_ROOT / image_path
    digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
    if not media.get("sha256") or digest != media["sha256"]:
        raise PermissionError("Approved image bytes do not match the target payload")
    image = social_image.SocialImage(
        image_path.read_bytes(),
        media_type="image/png" if image_path.suffix.lower() == ".png" else "image/jpeg",
        extension=image_path.suffix.lstrip(".") or "png",
        visual_description=media.get("visual_description", ""),
        source_page_url=media.get("source_page_url", ""),
        source_image_url=media.get("source_image_url", ""),
        creator=media.get("creator", ""),
        license_name=media.get("license_name", ""),
        license_url=media.get("license_url", ""),
        attribution=media.get("attribution", ""),
        source_type=media.get("source_type", "approved_visual"),
        generation_model=media.get("generation_model", ""),
        generation_prompt=media.get("generation_prompt", ""),
    )
    return image, ""


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
    seo_description = meta_description(content, CLIENT_PROFILE)
    destinations = []
    business = load_business_profile()
    canonical_targets = [
        targets[target_id]
        for target_id in ("canonical_wordpress", "canonical_wix")
        if target_id in targets
    ]
    if len(canonical_targets) != 1:
        raise RuntimeError(
            "Canonical approval bundle must contain exactly one CMS target"
        )
    canonical_target = canonical_targets[0]
    canonical_payload = canonical_target["payload"]
    approved_site_key = canonical_payload.get("site_key")
    primary = (
        site_by_key(business, approved_site_key)
        if approved_site_key
        else canonical_site(business)
    )
    if not primary or primary.get("platform", "wordpress") not in {
        "wordpress",
        "wix",
    }:
        raise RuntimeError("Approved publication site is not configured")
    primary_platform = primary.get("platform", "wordpress")
    expected_target_id = (
        "canonical_wix" if primary_platform == "wix" else "canonical_wordpress"
    )
    if canonical_target["target_id"] != expected_target_id:
        raise PermissionError("Approved CMS target does not match the configured site")
    canonical_base = primary["base_url"].rstrip("/")
    canonical_name = re.sub(r"^www\.", "", urlparse(canonical_base).netloc)
    if primary_platform == "wordpress":
        primary_user_env = primary["user_env"]
        primary_password_env = primary["app_password_env"]
        if not configured(primary_user_env, primary_password_env):
            raise RuntimeError("Canonical WordPress publisher is not configured")
    else:
        if not wix_blog.configured(primary):
            raise RuntimeError("Canonical Wix publisher is not configured")

    if canonical_payload["title"] != title or canonical_payload["markdown"] != content:
        raise PermissionError("Canonical content differs from the approved payload")
    hosted_images = {}
    media_host = (
        primary
        if primary_platform == "wordpress"
        else site_by_key(business, "GUYROFE_COM")
    )
    if not media_host or media_host.get("platform", "wordpress") != "wordpress":
        raise RuntimeError("Approved image hosting site is not configured")
    media_user_env = media_host["user_env"]
    media_password_env = media_host["app_password_env"]

    def approved_target_image(target):
        media = (target.get("payload") or {}).get("image") or approved_bundle.get("media")
        image, remote_url = _load_approved_local_image(media)
        if remote_url:
            return image, remote_url
        digest = media["sha256"]
        if digest not in hosted_images:
            if not configured(media_user_env, media_password_env):
                raise RuntimeError(
                    "WordPress media host is required for approved local Wix images"
                )
            role = media.get("role", "approved")
            hosted_images[digest] = social_image.upload_to_wordpress(
                image,
                base_url=media_host["base_url"].rstrip("/"),
                username=os.environ[media_user_env],
                app_password=os.environ[media_password_env],
                slug=(
                    f"{CLIENT_PROFILE['client_id']}-{draft_path.stem}-"
                    f"{role}"
                ),
                title=title,
            )
        return image, hosted_images[digest]

    try:
        canonical_image, canonical_image_url = approved_target_image(canonical_target)
    except Exception as exc:
        raise CampaignTargetError(canonical_name, exception_detail(exc)) from exc
    canonical_alt = (canonical_payload.get("image") or {}).get("alt_text", "")
    hero_html = (
        f'<figure><img src="{html.escape(canonical_image_url)}" '
        f'alt="{html.escape(canonical_alt)}" width="1600" height="900"></figure>\n'
    )
    try:
        if primary_platform == "wordpress":
            canonical_receipt = ledger.execute(
                approved_bundle,
                canonical_target,
                lambda payload, key: {
                    "url": wordpress_publish(
                        canonical_base,
                        os.environ[primary_user_env],
                        os.environ[primary_password_env],
                        payload["title"],
                        hero_html + markdown_to_html(payload["markdown"]),
                        idempotency_key=payload["slug"],
                        meta_description=seo_description,
                        article_schema_factory=lambda article_url: build_article_schema(
                            business,
                            headline=payload["title"],
                            article_url=article_url,
                            description=seo_description,
                            image_url=canonical_image_url,
                            citations=extract_citation_urls(payload["markdown"]),
                        ),
                    )
                },
            )
        else:
            canonical_receipt = ledger.execute(
                approved_bundle,
                canonical_target,
                lambda payload, key: {
                    "url": wix_blog.publish(
                        primary,
                        title=payload["title"],
                        html=hero_html + markdown_to_html(payload["markdown"]),
                        excerpt=seo_description,
                        slug=payload["slug"],
                        expected_url=payload["canonical_url"],
                    )
                },
                reconciler=lambda payload, key: wix_blog.reconcile(
                    primary,
                    slug=payload["slug"],
                    expected_url=payload["canonical_url"],
                ),
            )
    except Exception as exc:
        raise CampaignTargetError(canonical_name, str(exc)) from exc
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
            target_id=canonical_target["target_id"],
        )
    )

    google_token = None
    google_token_error = None
    if (
        targets.get("blogger_blog") or targets.get("google_business_profile")
    ) and (blogger.is_configured() or google_business.is_configured()):
        try:
            google_token = google_oauth.refresh_access_token()
        except google_oauth.GoogleOAuthError as exc:
            google_token_error = str(exc)
            log(google_token_error)
    log(f"Canonical article published: {canonical_url}")
    destinations.append(
        destination(
            "Canonical editorial hero",
            "hosted",
            url=canonical_image_url,
            detail=canonical_image.source_type if canonical_image else "approved_remote",
        )
    )

    # Every other owned site remains untouched. There is no implicit echo,
    # cross-domain fan-out or rephrased duplicate publication.
    for site in business["sites"]:
        if site is primary:
            continue
        name = re.sub(r"^www\.", "", urlparse(site["base_url"]).netloc)
        detail = "לא אושר בחבילה זו; אין שכפול אוטומטי בין נכסים"
        if site.get("audit_status") == "required":
            detail = "חסום לפרסום עד השלמת ביקורת התוכן הישן"
        destinations.append(
            destination(name, "not_in_approval_bundle", detail=detail)
        )

    enforce_channel_policy("Facebook")
    facebook_target = targets.get("facebook_page")
    if not facebook_target:
        destinations.append(destination("Facebook", "not_scheduled"))
    elif meta.facebook_is_configured():
        facebook_image, facebook_image_url = approved_target_image(facebook_target)
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
                        facebook_image_url,
                        (payload.get("image") or {}).get("alt_text"),
                        payload.get("disclosure"),
                    )
                },
            )
        )
    else:
        destinations.append(destination("Facebook", "not_configured"))
    linkedin_target = targets.get("linkedin_member")
    if not linkedin_target:
        destinations.append(destination("LinkedIn", "not_scheduled"))
    elif linkedin.is_configured():
        linkedin_image, linkedin_image_url = approved_target_image(linkedin_target)
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
                        linkedin_image.content if linkedin_image else None,
                        (payload.get("image") or {}).get("alt_text"),
                        payload.get("disclosure"),
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
    blogger_target = targets.get("blogger_blog")
    if not blogger_target:
        destinations.append(destination("Blogger", "not_scheduled"))
    elif google_token_error:
        destinations.append(
            destination("Blogger", "failed", detail=google_token_error)
        )
    elif blogger.is_configured():
        blogger_image, blogger_image_url = approved_target_image(blogger_target)
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
                        blogger_image_url,
                        (payload.get("image") or {}).get("alt_text"),
                        payload.get("disclosure"),
                        access_token=google_token,
                    )
                },
                reconciler=lambda payload, key: blogger.reconcile(
                    payload["title"],
                    canonical_url,
                    access_token=google_token,
                ),
            )
        )
    else:
        destinations.append(destination("Blogger", "not_configured"))

    instagram_target = targets.get("instagram_business")
    if not instagram_target:
        destinations.append(destination("Instagram", "not_scheduled"))
    elif meta.instagram_is_configured():
        instagram_image, instagram_image_url = approved_target_image(
            instagram_target
        )
        destinations.append(
            _execute_target_safely(
                ledger,
                approved_bundle,
                instagram_target,
                lambda payload, key: {
                    "url": meta.publish_instagram(
                        payload["title"],
                        payload["text"],
                        canonical_url,
                        instagram_image_url,
                        payload.get("disclosure"),
                    )
                },
            )
        )
    else:
        destinations.append(destination("Instagram", "not_configured"))
    pinterest_target = targets.get("pinterest_board")
    if not pinterest_target:
        destinations.append(destination("Pinterest", "not_scheduled"))
    elif pinterest.is_configured():
        pinterest_image, pinterest_image_url = approved_target_image(pinterest_target)
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
                        pinterest_image_url,
                        (payload.get("image") or {}).get("alt_text"),
                        payload.get("disclosure"),
                    )
                },
            )
        )
    else:
        destinations.append(
            destination(
                "Pinterest",
                "not_configured",
            )
        )

    google_business_target = targets.get("google_business_profile")
    if not google_business_target:
        destinations.append(
            destination("Google Business Profile", "not_scheduled")
        )
    elif google_token_error:
        destinations.append(
            destination(
                "Google Business Profile",
                "failed",
                detail=google_token_error,
            )
        )
    else:
        enforce_channel_policy("Google Business Profile")
        google_payload = google_business_target["payload"]
        if google_payload.get("topic_type") != "STANDARD":
            raise PermissionError(
                "Google Business is limited to approved STANDARD information posts"
            )
        if google_payload.get("call_to_action") != "LEARN_MORE":
            raise PermissionError(
                "Google Business is limited to the LEARN_MORE action"
            )
        if google_payload.get("link", "").rstrip("/") != canonical_url.rstrip("/"):
            raise PermissionError(
                "Google Business link differs from the approved canonical URL"
            )
        if google_business.is_configured():
            _google_image, google_image_url = approved_target_image(
                google_business_target
            )
            destinations.append(
                _execute_target_safely(
                    ledger,
                    approved_bundle,
                    google_business_target,
                    lambda payload, key: google_business.publish(
                        payload["summary"],
                        payload["link"],
                        google_image_url,
                        language_code=payload.get("language_code", "he"),
                        access_token=google_token,
                    ),
                    reconciler=lambda payload, key: google_business.reconcile(
                        payload["summary"],
                        payload["link"],
                        google_image_url,
                        language_code=payload.get("language_code", "he"),
                        access_token=google_token,
                    ),
                )
            )
        else:
            destinations.append(
                destination("Google Business Profile", "not_configured")
            )

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
            destination_name = (
                exc.destination_name
                if isinstance(exc, CampaignTargetError)
                else "Campaign"
            )
            write_campaign_result(
                draft_path,
                title,
                [destination(destination_name, "failed", detail=exception_detail(exc))],
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
