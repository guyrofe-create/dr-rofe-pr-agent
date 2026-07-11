#!/usr/bin/env python3
"""Compare the declared secret manifest with names available in the environment.

The script never reads or prints secret values.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "config" / "secrets_manifest.json"


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    missing_total = 0
    for connection in manifest["connections"]:
        required = connection.get("required", [])
        missing = [name for name in required if not os.environ.get(name)]
        missing_total += len(missing)
        state = "READY" if not missing else "MISSING"
        print(f"{state:7} {connection['platform']}")
        for name in missing:
            print(f"        - {name}")
    print(f"\nMissing secret names: {missing_total}")


if __name__ == "__main__":
    main()
