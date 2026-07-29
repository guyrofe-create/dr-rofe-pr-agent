#!/usr/bin/env python3
"""Read-only Meta connection check; never prints access tokens."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import meta


def main():
    ok, detail = meta.check_token_health()
    print(f"{'PASS' if ok else 'FAIL'} Facebook Page access: {detail}")
    read_ok, read_detail = meta.check_recent_posts_access()
    print(
        f"{'PASS' if read_ok else 'FAIL'} Facebook recent-post read access: "
        f"{str(read_detail)[:240]}"
    )
    instagram, instagram_detail = meta.get_linked_instagram_account()
    if instagram:
        print(
            "PASS Linked Instagram professional account: "
            f"@{instagram.get('username')} id={instagram.get('id')}"
        )
    else:
        print(f"INFO Linked Instagram professional account: {instagram_detail}")
    print("INFO Instagram publishing: disabled (owner-managed pilot channel)")
    return 0 if ok and read_ok else 1


if __name__ == "__main__":
    sys.exit(main())
