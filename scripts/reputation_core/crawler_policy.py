"""Read-only crawler accessibility checks for search visibility."""
from __future__ import annotations

from dataclasses import dataclass
from urllib import robotparser


SEARCH_CRAWLERS = ("Googlebot", "Bingbot", "OAI-SearchBot", "PerplexityBot")


@dataclass(frozen=True)
class CrawlerCheck:
    user_agent: str
    allowed: bool
    note: str


def audit_robots_text(robots_text: str, site_url: str) -> list[CrawlerCheck]:
    parser = robotparser.RobotFileParser()
    parser.set_url(site_url.rstrip("/") + "/robots.txt")
    parser.parse((robots_text or "").splitlines())
    target = site_url.rstrip("/") + "/"
    return [
        CrawlerCheck(
            user_agent=agent,
            allowed=parser.can_fetch(agent, target),
            note=(
                "crawl allowed; visibility is not guaranteed"
                if parser.can_fetch(agent, target)
                else "blocked by robots.txt"
            ),
        )
        for agent in SEARCH_CRAWLERS
    ]


def recommended_robots_block() -> str:
    return "\n".join(
        [
            "# Search visibility crawlers; allowing access does not guarantee inclusion.",
            "User-agent: OAI-SearchBot",
            "Allow: /",
            "",
            "User-agent: PerplexityBot",
            "Allow: /",
        ]
    )

