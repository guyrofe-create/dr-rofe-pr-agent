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
    ig_ok, ig_detail = meta.check_instagram_account_access()
    print(
        f"{'PASS' if ig_ok else 'FAIL'} Instagram Business access: "
        f"{str(ig_detail)[:240]}"
    )
    return 0 if ig_ok else 1


if __name__ == "__main__":
    sys.exit(main())
