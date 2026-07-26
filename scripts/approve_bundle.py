#!/usr/bin/env python3
"""Record an explicit P7 approval. The signing secret belongs server-side."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from reputation_core.approval_workflow import approve_bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_path")
    parser.add_argument("--approved-by", required=True)
    parser.add_argument(
        "--scope",
        action="append",
        required=True,
        help="Repeat for every explicitly approved scope.",
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    secret = os.environ.get("APPROVAL_SIGNING_SECRET", "")
    if not secret:
        raise RuntimeError("APPROVAL_SIGNING_SECRET is required")
    bundle_path = Path(args.bundle_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    record = approve_bundle(
        bundle,
        approved_by=args.approved_by,
        approved_scopes=args.scope,
        signing_secret=secret,
    )
    output = Path(args.output or bundle_path.with_suffix(".approval.json"))
    output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
