#!/usr/bin/env python3
"""Read-only Meta connection check; never prints access tokens."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta


def main():
    ok, detail = meta.check_token_health()
    print(f"{'PASS' if ok else 'FAIL'} Facebook Page access: {detail}")
    print("INFO Instagram publishing: disabled (owner-managed pilot channel)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
