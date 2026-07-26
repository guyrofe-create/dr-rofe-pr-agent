#!/usr/bin/env python3
"""Publish one explicitly approved LinkedIn post."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from social_publishers import linkedin


def main():
    text = os.environ.get("LINKEDIN_POST_TEXT", "").strip()
    confirm = os.environ.get("LINKEDIN_CONFIRM_PUBLISH", "").strip().lower()
    if confirm != "true":
        print("LinkedIn: SAFE STOP -> publish confirmation is not true")
        raise SystemExit(1)
    if not text:
        print("LinkedIn: SAFE STOP -> post text is empty")
        raise SystemExit(1)
    result_url = linkedin.publish("", text)
    print(f"LinkedIn: PUBLISHED -> {result_url}")


if __name__ == "__main__":
    main()
