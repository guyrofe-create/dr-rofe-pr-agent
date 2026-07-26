"""Select news opportunities and turn them into original evidence-led briefs."""
from __future__ import annotations

from datetime import datetime, timezone


TRUSTED_SOURCE_KINDS = {
    "official": 5,
    "peer_reviewed": 5,
    "major_news": 3,
    "professional_body": 4,
    "other": 1,
}


def score_news_candidate(candidate: dict, now: datetime | None = None) -> dict:
    """Score attention opportunity, not medical truth; truth is reviewed separately."""
    now = now or datetime.now(timezone.utc)
    published = candidate.get("published_at")
    age_hours = 72
    if published:
        try:
            parsed = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
            age_hours = max(0, (now - parsed).total_seconds() / 3600)
        except (TypeError, ValueError):
            pass
    recency = 5 if age_hours <= 12 else 4 if age_hours <= 24 else 2 if age_hours <= 72 else 0
    attention = min(5, int(candidate.get("attention_score", 0)))
    relevance = min(5, int(candidate.get("public_health_relevance", 0)))
    evidence = TRUSTED_SOURCE_KINDS.get(candidate.get("source_kind", "other"), 1)
    evidence += 2 if candidate.get("primary_source_url") else 0
    analysis_gap = min(5, int(candidate.get("analysis_gap", 0)))
    sensationalism = min(5, int(candidate.get("sensationalism_risk", 0)))
    score = recency * 2 + attention * 2 + relevance * 3 + evidence * 3 + analysis_gap * 2 - sensationalism * 3
    eligible = bool(
        candidate.get("url")
        and candidate.get("title")
        and relevance >= 2
        and score >= 25
        and not candidate.get("prohibited")
    )
    return {
        **candidate,
        "age_hours": round(age_hours, 1),
        "opportunity_score": score,
        "eligible": eligible,
        "requires_primary_source_research": not bool(candidate.get("primary_source_url")),
        "requires_medical_review": True,
    }


def rank_news_candidates(candidates: list[dict], limit: int = 5) -> list[dict]:
    scored = [score_news_candidate(candidate) for candidate in candidates]
    eligible = [candidate for candidate in scored if candidate["eligible"]]
    return sorted(
        eligible,
        key=lambda item: (-item["opportunity_score"], item["age_hours"]),
    )[:limit]


def build_news_analysis_brief(candidate: dict) -> dict:
    scored = score_news_candidate(candidate)
    if not scored["eligible"]:
        raise ValueError("news candidate does not meet the evidence-led opportunity threshold")
    return {
        "asset_blueprint": "health_news_analysis_desk",
        "destination_role": "Hebrew evidence-based medical news and explainers",
        "working_title": f"מה עומד מאחורי הכותרת: {candidate['title']}",
        "analyzed_news_url": candidate["url"],
        "primary_source_url": candidate.get("primary_source_url"),
        "required_sections": [
            "הכותרת שעלתה היום",
            "מה פורסם ומה נטען",
            "הנתונים או המחקר שעליהם נשענת הכתבה",
            "מה נכון בכותרת",
            "מה חסר או דורש הסתייגות",
            "המשמעות המעשית לציבור",
            "מגבלות ואי־ודאות",
            "מקורות",
        ],
        "editorial_requirements": [
            "Link visibly to the analyzed news article",
            "Use at least two direct authoritative sources in addition to the news link",
            "Add original analysis and do not reproduce the article",
            "State uncertainty and distinguish association from causation",
            "Use a descriptive, non-sensational headline",
            "Information only; no consultation, treatment or appointment invitation",
            "Human medical review before publication",
        ],
        "distribution": [
            "Publish the canonical analysis on drguyrofe.co.il",
            "Create distinct native summaries for approved managed platforms",
            "Use an original image or chart with natural alt text when useful",
        ],
        "opportunity_score": scored["opportunity_score"],
        "status": "draft_brief_requires_editorial_review",
    }
