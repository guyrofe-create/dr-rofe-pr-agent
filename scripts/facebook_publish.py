#!/usr/bin/env python3
"""Publish one explicitly approved Facebook Page post through the product."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from publication_policy import enforce_publication_policy
from social_publishers import meta


def main():
    body = os.environ["FACEBOOK_POST_TEXT"].strip()
    url = os.environ.get("FACEBOOK_POST_URL", "").strip()
    enforce_publication_policy(body)
    result = meta.publish_facebook("", body, url)
    print(f"PASS Facebook published through product: {result}")


if __name__ == "__main__":
    main()
