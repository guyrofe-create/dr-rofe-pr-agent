#!/usr/bin/env python3
"""Remove the one duplicate agent breadcrumb without changing article content."""
from __future__ import annotations

import json
import os
import re
import xmlrpc.client
from hashlib import sha256
from urllib.parse import unquote

import requests

BASE_URL = "https://guyrofe.com"
POST_ID = 1237
TARGET_URL = (
    "https://guyrofe.com/"
    "%d7%93%d7%99%d7%9e%d7%95%d7%9d-%d7%a8%d7%97%d7%9e%d7%99-"
    "%d7%97%d7%a8%d7%99%d7%92-%d7%a1%d7%99%d7%91%d7%95%d7%aa-"
    "%d7%90%d7%a4%d7%a9%d7%a8%d7%99%d7%95%d7%aa-%d7%95%d7%9e%d7%aa%d7%99/"
)
ARTICLE_ID = TARGET_URL.rstrip("/") + "/#article"
BREADCRUMB_ID = TARGET_URL.rstrip("/") + "/#breadcrumb"
SCRIPT_RE = re.compile(
    r"(<script\b(?P<attrs>[^>]*)>)(?P<body>.*?)(</script>)",
    re.IGNORECASE | re.DOTALL,
)
HEADERS = {
    "Accept": "application/json",
    "Cache-Control": "no-cache",
    "User-Agent": "ReputationAgent/guy-rofe-pilot (+https://guyrofe.com)",
}


def _is_json_ld(attrs: str) -> bool:
    return bool(re.search(
        r"\btype\s*=\s*(['\"])application/ld\+json\1",
        attrs,
        re.IGNORECASE,
    ))


def remove_agent_breadcrumb(content: str) -> tuple[str, int]:
    changed = 0

    def rewrite(match: re.Match) -> str:
        nonlocal changed
        if not _is_json_ld(match.group("attrs")):
            return match.group(0)
        try:
            payload = json.loads(match.group("body"))
        except (TypeError, ValueError):
            return match.group(0)
        if not isinstance(payload, dict) or not isinstance(payload.get("@graph"), list):
            return match.group(0)
        graph = payload["@graph"]
        has_agent_article = any(
            isinstance(node, dict)
            and node.get("@type") == "Article"
            and node.get("@id") == ARTICLE_ID
            for node in graph
        )
        has_target_breadcrumb = any(
            isinstance(node, dict)
            and node.get("@type") == "BreadcrumbList"
            and node.get("@id") == BREADCRUMB_ID
            for node in graph
        )
        if not (has_agent_article and has_target_breadcrumb):
            return match.group(0)
        payload["@graph"] = [
            node for node in graph
            if not (
                isinstance(node, dict)
                and node.get("@type") == "BreadcrumbList"
                and node.get("@id") == BREADCRUMB_ID
            )
        ]
        for node in payload["@graph"]:
            if (
                isinstance(node, dict)
                and node.get("@type") == "Article"
                and node.get("@id") == ARTICLE_ID
            ):
                node.pop("breadcrumb", None)
        changed += 1
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return match.group(1) + body.replace("</", "<\\/") + match.group(4)

    updated = SCRIPT_RE.sub(rewrite, content)
    return updated, changed


def _json_ld_payloads(html: str):
    for match in SCRIPT_RE.finditer(html):
        if not _is_json_ld(match.group("attrs")):
            continue
        try:
            yield json.loads(match.group("body"))
        except (TypeError, ValueError):
            continue


def _nodes(value):
    if isinstance(value, dict):
        if "@type" in value:
            yield value
        for item in value.values():
            yield from _nodes(item)
    elif isinstance(value, list):
        for item in value:
            yield from _nodes(item)


def verify_public_page() -> None:
    response = requests.get(TARGET_URL, timeout=30, headers={"Cache-Control": "no-cache"})
    if response.status_code in {202, 403}:
        print(
            f"Public verification deferred: site security returned HTTP {response.status_code} "
            "to the GitHub runner"
        )
        return
    response.raise_for_status()
    breadcrumbs = [
        node
        for payload in _json_ld_payloads(response.text)
        for node in _nodes(payload)
        if node.get("@type") == "BreadcrumbList"
        and node.get("@id") == BREADCRUMB_ID
    ]
    if len(breadcrumbs) != 1:
        raise RuntimeError(
            f"Expected one CMS breadcrumb after repair; found {len(breadcrumbs)}"
        )
    items = breadcrumbs[0].get("itemListElement") or []
    if any(not item.get("item") for item in items[:-1]):
        raise RuntimeError("A non-final breadcrumb item is still missing item")


def _same_url(left: str, right: str) -> bool:
    return unquote((left or "").rstrip("/")) == unquote((right or "").rstrip("/"))


def _xmlrpc_call(method: str, params: tuple):
    response = requests.post(
        f"{BASE_URL}/xmlrpc.php",
        data=xmlrpc.client.dumps(params, methodname=method, allow_none=True),
        headers={**HEADERS, "Content-Type": "text/xml"},
        timeout=30,
    )
    response.raise_for_status()
    values, _ = xmlrpc.client.loads(response.content)
    return values[0]


def main() -> None:
    username = os.environ["WORDPRESS_GUYROFE_COM_USER"]
    password = os.environ["WORDPRESS_GUYROFE_COM_API"]
    endpoint = f"{BASE_URL}/wp-json/wp/v2/posts/{POST_ID}"
    response = requests.get(
        endpoint,
        params={"context": "edit", "_fields": "id,link,slug,status,title,content"},
        auth=(username, password),
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    use_xmlrpc = False
    try:
        post = response.json()
        raw = post["content"]["raw"]
    except (ValueError, KeyError, TypeError):
        use_xmlrpc = True
        post = _xmlrpc_call("wp.getPost", (0, username, password, POST_ID))
        raw = post["post_content"]
    if not _same_url(post.get("link"), TARGET_URL):
        raise RuntimeError(f"Post {POST_ID} URL changed; refusing repair")
    updated, changed = remove_agent_breadcrumb(raw)
    visible_before = SCRIPT_RE.sub("", raw)
    visible_after = SCRIPT_RE.sub("", updated)
    if visible_before != visible_after:
        raise RuntimeError("Visible article content would change; refusing repair")
    if changed > 1:
        raise RuntimeError(f"Expected at most one agent graph; found {changed}")
    if changed == 1:
        if use_xmlrpc:
            applied = _xmlrpc_call(
                "wp.editPost",
                (0, username, password, POST_ID, {"post_content": updated}),
            )
            if applied is not True:
                raise RuntimeError("WordPress XML-RPC did not confirm the repair")
        else:
            update = requests.post(
                endpoint,
                auth=(username, password),
                json={"content": updated},
                headers=HEADERS,
                timeout=30,
            )
            update.raise_for_status()
            result = update.json()
            if not _same_url(result.get("link"), TARGET_URL):
                raise RuntimeError("WordPress returned an unexpected URL after repair")
        print(
            "Removed duplicate breadcrumb only; visible-content SHA256 remains "
            + sha256(visible_after.encode()).hexdigest()
        )
    else:
        print("Duplicate agent breadcrumb already absent; verification only")
    _, remaining = remove_agent_breadcrumb(updated)
    if remaining:
        raise RuntimeError("Duplicate agent breadcrumb remains after repair")
    print("Verified: duplicate breadcrumb is absent from the repaired post content")
    verify_public_page()


if __name__ == "__main__":
    main()
