#!/usr/bin/env python3
"""Read-only public reachability check for every registered asset URL."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]


def classify(status: int | None, error: str | None) -> str:
    if error:
        return "network_or_provider_error"
    if status is None:
        return "unknown"
    if 200 <= status < 400:
        return "reachable"
    if status in {401, 403, 418, 429}:
        return "access_restricted_or_anti_bot"
    if status in {404, 410}:
        return "not_found"
    return "http_error"


def check(asset: dict, *, timeout: int = 12) -> dict:
    url = asset.get("url")
    if not url:
        return {"platform": asset.get("platform"), "url": None,
                "http_status": None, "reachability": "missing_url"}
    try:
        response = requests.get(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; reputation-asset-audit/1.0)"},
            stream=True,
        )
        status = response.status_code
        final_url = response.url
        response.close()
        return {
            "platform": asset.get("platform"), "url": url,
            "http_status": status, "final_url": final_url,
            "reachability": classify(status, None),
        }
    except requests.RequestException as exc:
        return {
            "platform": asset.get("platform"), "url": url,
            "http_status": None, "reachability": classify(None, str(exc)),
            "error_type": type(exc).__name__,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "data" / "asset_registry.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    assets = registry.get("assets", [])
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
        futures = [pool.submit(check, asset) for asset in assets]
        for future in as_completed(futures):
            rows.append(future.result())
    order = {asset.get("platform"): index for index, asset in enumerate(assets)}
    rows.sort(key=lambda row: order.get(row.get("platform"), 9999))
    counts = {}
    for row in rows:
        key = row["reachability"]
        counts[key] = counts.get(key, 0) + 1
    payload = {
        "version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "asset_count": len(rows),
        "summary": counts,
        "credentials_used": False,
        "public_changes_made": False,
        "assets": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset_count": len(rows), "summary": counts}))


if __name__ == "__main__":
    main()
