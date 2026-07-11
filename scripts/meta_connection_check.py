#!/usr/bin/env python3
"""Read-only Meta connection check; never prints access tokens."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta


def main():
    ok, detail = meta.check_token_health()
    print(f"{'PASS' if ok else 'FAIL'} Facebook Page access: {detail}")
    if not ok:
        return 1
    try:
        ig_id = meta.resolve_instagram_business_id()
        print(f"PASS Instagram Business link: account ending {ig_id[-4:]}")
        return 0
    except Exception as exc:
        print(f"FAIL Instagram Business link: {str(exc)[:240]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
