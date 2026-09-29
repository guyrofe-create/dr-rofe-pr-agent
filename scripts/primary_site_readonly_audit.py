#!/usr/bin/env python3
"""Read-only canonical-site audit. This script has no write or CMS capability."""
from __future__ import annotations

import argparse
import json
import re
from html import unescape

import requests

from reputation_core.technical_visibility import audit_structured_data


def _text(html: str) -> str:
    html = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.I | re.S)
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def audit_homepage(html: str, final_url: str, status_phrases: list[str]) -> dict:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    canonical = re.search(
        r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',
        html,
        re.I,
    )
    headings = [
        " ".join(unescape(re.sub(r"<[^>]+>", " ", item)).split())
        for item in re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.I | re.S)
    ]
    visible = _text(html)
    lower = visible.casefold()
    signals = {
        "books": any(item in lower for item in ("ספר", "books")),
        "podcast": any(item in lower for item in ("פודקאסט", "podcast", "spotify")),
        "not_accepting_patients": any(item.casefold() in lower for item in status_phrases),
        "appointment_or_patient_acquisition": any(item in lower for item in (
            "קביעת תור", "לקביעת תור", "מקבל מטופלות", "appointment", "book now"
        )),
    }
    return {
        "url": final_url,
        "title": unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else None,
        "canonical": canonical.group(1) if canonical else None,
        "h1": headings,
        "signals": signals,
        "structured_data": audit_structured_data(html),
        "recommendation_gate": (
            "Do not change title, H1, canonical, URL, navigation or homepage copy "
            "without an exact separately approved change and before/after measurement."
        ),
        "public_write_performed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://guyrofe.com/")
    parser.add_argument("--output")
    args = parser.parse_args()
    response = requests.get(
        args.url,
        timeout=30,
        headers={"User-Agent": "ReputationAgent-CanonicalAudit/1.0"},
    )
    response.raise_for_status()
    report = audit_homepage(
        response.text,
        response.url,
        ["אינו מקבל מטופלות", "איני מקבל מטופלות", "not accepting patients"],
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")


if __name__ == "__main__":
    main()
