"""Read-only crawler accessibility checks for search visibility."""
from __future__ import annotations

from dataclasses import dataclass
from urllib import robotparser


CRAWLER_ROLES = {
    "Googlebot": "google_search_and_ai_overviews",
    "Google-Extended": "google_non_search_ai_training_and_grounding",
    "Bingbot": "bing_search",
    "OAI-SearchBot": "openai_search",
    "GPTBot": "openai_model_training",
    "ChatGPT-User": "openai_user_requested_fetch",
    "PerplexityBot": "perplexity_search",
    "Perplexity-User": "perplexity_user_requested_fetch",
    "ClaudeBot": "anthropic_model_training",
    "Claude-SearchBot": "anthropic_search",
    "Claude-User": "anthropic_user_requested_fetch",
}
SEARCH_CRAWLERS = tuple(CRAWLER_ROLES)
VISIBILITY_CRAWLERS = tuple(
    agent
    for agent, role in CRAWLER_ROLES.items()
    if "training" not in role and "non_search_ai" not in role
)


@dataclass(frozen=True)
class CrawlerCheck:
    user_agent: str
    allowed: bool
    note: str
    role: str


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
            role=CRAWLER_ROLES[agent],
        )
        for agent in SEARCH_CRAWLERS
    ]


def recommended_robots_block() -> str:
    return "\n".join(
        [
            "# Search visibility crawlers; allowing access does not guarantee inclusion.",
            "# Training-only crawlers are intentionally omitted; handle them as a separate policy choice.",
            *[
                line
                for agent in VISIBILITY_CRAWLERS
                for line in (f"User-agent: {agent}", "Allow: /", "")
            ],
        ]
    ).rstrip()
