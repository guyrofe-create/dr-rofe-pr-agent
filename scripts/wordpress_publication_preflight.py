#!/usr/bin/env python3
"""Read-only WordPress gateway check used before consuming an approval.

The check never authenticates and never sends a write. A temporary HTML/WAF
response exits with 75 so the scheduled workflow can leave the approval queue
untouched and try again later from a fresh runner.
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFERRED_EXIT = 75
USER_AGENT = "ReputationAgentPublisher/1.0 (+https://guyrofe.com)"


def _routes(base_url: str) -> list[str]:
    root = base_url.rstrip("/")
    query = urlencode(
        {
            "slug": "reputation-agent-read-only-preflight",
            "_fields": "id,slug",
        }
    )
    return [
        f"{root}/wp-json/wp/v2/media?{query}",
        f"{root}/?{urlencode({'rest_route': '/wp/v2/media'})}&{query}",
        f"{root}/index.php?{urlencode({'rest_route': '/wp/v2/media'})}&{query}",
    ]


def check(base_url: str, *, opener=urlopen, timeout: int = 20) -> tuple[bool, str]:
    diagnostics: list[str] = []
    for route in _routes(base_url):
        request = Request(
            route,
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": USER_AGENT,
            },
            method="GET",
        )
        try:
            with opener(request, timeout=timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                content_type = str(response.headers.get("Content-Type") or "")
                body = response.read(1_000_000)
        except HTTPError as exc:
            status = exc.code
            content_type = str(exc.headers.get("Content-Type") or "")
            body = exc.read(1_000_000)
        except (URLError, TimeoutError, OSError) as exc:
            diagnostics.append(f"{type(exc).__name__}: {exc}")
            continue
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        diagnostics.append(f"HTTP {status} {content_type or 'unknown'}")
        if status == 200 and isinstance(payload, list):
            return True, diagnostics[-1]
    return False, "; ".join(diagnostics)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()
    healthy, detail = check(args.base_url, timeout=args.timeout)
    if healthy:
        print(f"WordPress publication gateway is ready: {detail}")
        return
    print(
        "WordPress publication gateway is temporarily unavailable; "
        f"approval queue was not consumed: {detail}",
        file=sys.stderr,
    )
    raise SystemExit(DEFERRED_EXIT)


if __name__ == "__main__":
    main()
