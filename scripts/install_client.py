#!/usr/bin/env python3
"""Create one isolated, configurable Reputation Agent installation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reputation_core.onboarding import (
    build_installation_files,
    validate_installation_files,
    write_installation,
)


PRODUCT_ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    strategy = json.loads(
        (PRODUCT_ROOT / "config" / "reputation_strategy.json").read_text(
            encoding="utf-8"
        )
    )
    files = build_installation_files(spec, strategy)
    written = write_installation(args.destination, files, force=args.force)
    result = validate_installation_files(args.destination)
    if result["status"] != "ready":
        raise SystemExit("; ".join(result["errors"]))
    print(f"Installation ready: {args.destination.resolve()}")
    print(f"Client: {spec['display_name']} ({spec['client_id']})")
    print(f"Generated {len(written)} isolated configuration/data files.")
    print("No secret values were written.")


if __name__ == "__main__":
    main()
