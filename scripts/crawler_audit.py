#!/usr/bin/env python3
"""Read-only robots.txt audit for search and answer-engine crawlers."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import requests

from reputation_core.crawler_policy import audit_robots_text
from reputation_core.installation import data_path


def audit_site(site: dict, *, session=requests) -> dict:
    base_url = site["base_url"].rstrip("/")
    robots_url = base_url + "/robots.txt"
    try:
        response = session.get(
            robots_url,
            headers={"User-Agent": "ReputationAgentCrawlerAudit/1.0"},
            timeout=20,
        )
        if response.status_code == 404:
            robots_text = ""
            status = "not_found_default_allow"
        else:
            response.raise_for_status()
            robots_text = response.text
            status = "ok"
        checks = audit_robots_text(robots_text, base_url)
        return {
            "site": site["key"],
            "url": base_url,
            "robots_url": robots_url,
            "status": status,
            "checks": [
                {
                    "user_agent": item.user_agent,
                    "allowed": item.allowed,
                    "note": item.note,
                }
                for item in checks
            ],
        }
    except Exception as exc:
        return {
            "site": site["key"],
            "url": base_url,
            "robots_url": robots_url,
            "status": "unreachable",
            "error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "checks": [],
        }


def main() -> None:
    profile = json.loads(data_path("business_profile.json").read_text(encoding="utf-8"))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_search_crawler_access",
        "guarantee": False,
        "sites": [audit_site(site) for site in profile.get("sites", [])],
    }
    with open("crawler_audit.json", "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    blocked = [
        f"{site['site']}:{check['user_agent']}"
        for site in report["sites"]
        for check in site.get("checks", [])
        if not check["allowed"]
    ]
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if blocked:
        print("WARNING blocked search crawlers: " + ", ".join(blocked))


if __name__ == "__main__":
    main()
