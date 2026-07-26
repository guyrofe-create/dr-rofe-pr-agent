#!/usr/bin/env python3
"""Read-only LinkedIn OAuth and member identity check."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import linkedin


def main():
    if not linkedin.is_configured():
        print("LinkedIn: MISSING LINKEDIN_ACCESS_TOKEN")
        raise SystemExit(1)
    try:
        member = linkedin.current_member()
    except Exception as exc:
        print(f"LinkedIn: FAILED -> {exc}")
        raise SystemExit(1)
    print(f"LinkedIn: READY -> {member['name'] or 'authenticated member'}")
    print(f"LinkedIn person URN resolved: {member['person_urn']}")


if __name__ == "__main__":
    main()
