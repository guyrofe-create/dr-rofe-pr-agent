#!/usr/bin/env python3
"""Create a review-only media brief for one verified podcast transcript."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "podcast_sources.json"
DEFAULT_OUTPUT = ROOT / "opportunity_drafts" / "media"


def _valid_episode_url(url: str, host: str) -> bool:
    parsed = urlparse(url)
    trusted_host = parsed.netloc == host or parsed.netloc.endswith(f".{host}")
    if parsed.scheme != "https" or not trusted_host:
        return False
    if host == "open.spotify.com":
        return parsed.path.startswith("/episode/") and len(parsed.path) > 9
    if host == "podcasts.apple.com":
        return bool(parse_qs(parsed.query).get("i"))
    return (
        parsed.netloc == host or parsed.netloc.endswith(f".{host}")
    )


def create_episode_brief(
    *,
    title: str,
    transcript_markdown: str,
    spotify_url: str,
    apple_url: str,
    published_at: str | None = None,
    config_path: Path = DEFAULT_CONFIG,
    output_dir: Path = DEFAULT_OUTPUT,
    now: datetime | None = None,
) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    show = next(
        item
        for item in config["shows"]
        if item["key"] == "REFUA_AL_KOS_CAFE"
    )
    if not title.strip():
        raise ValueError("Podcast episode title is required")
    transcript = transcript_markdown.strip()
    if not transcript:
        raise ValueError("A verified transcript is required")
    if not _valid_episode_url(spotify_url, "open.spotify.com"):
        raise ValueError("A valid Spotify episode URL is required")
    if not _valid_episode_url(apple_url, "podcasts.apple.com"):
        raise ValueError("A valid Apple Podcasts episode URL is required")
    episode_key = hashlib.sha256(
        f"{spotify_url.strip()}\n{apple_url.strip()}".encode("utf-8")
    ).hexdigest()[:16]
    created_at = (now or datetime.now(timezone.utc)).isoformat()
    brief = {
        "version": 1,
        "status": "transcript_ready_for_editorial_review",
        "destination_site_key": show["destination_site_key"],
        "content_stream": show["content_stream"],
        "podcast_key": show["key"],
        "podcast_title": show["title"],
        "creator": show["creator"],
        "working_title": title.strip(),
        "source_media_type": "podcast",
        "source_media_url": spotify_url.strip(),
        "platform_urls": {
            "spotify": spotify_url.strip(),
            "apple_podcasts": apple_url.strip()
        },
        "published_at": published_at,
        "transcript_markdown": transcript,
        "created_at": created_at,
        "public_execution_allowed": False,
        "publication_requires_exact_p7_approval": True
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"media-transcript-podcast-{episode_key}.json"
    path.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--title", required=True)
    parser.add_argument("--transcript", type=Path, required=True)
    parser.add_argument("--spotify-url", required=True)
    parser.add_argument("--apple-url", required=True)
    parser.add_argument("--published-at")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    path = create_episode_brief(
        title=args.title,
        transcript_markdown=args.transcript.read_text(encoding="utf-8"),
        spotify_url=args.spotify_url,
        apple_url=args.apple_url,
        published_at=args.published_at,
        config_path=args.config,
        output_dir=args.output_dir,
    )
    print(path)


if __name__ == "__main__":
    main()
