"""Deterministic reputation risk scoring and routing.

The scorer deliberately does not use an LLM. High-impact routing must remain
explainable, testable and available even when an external model is down.
"""
from dataclasses import dataclass
from typing import Iterable


CRISIS_TERMS = {
    "סכנה", "מוות", "פגיעה", "משטרה", "חקירה", "כתב אישום", "תביעה",
    "הטרדה", "אונס", "רשלנות", "fraud", "lawsuit", "indicted", "danger",
}
HARASSMENT_TERMS = {
    "כלא", "תא", "סבון", "יאנס", "איום", "מטרידנים", "kill", "threat",
}
OPERATIONAL_TERMS = {
    "המתנה", "שירות", "יחס", "מחיר", "לא ענו", "תור", "איחור", "זמינות",
}


@dataclass(frozen=True)
class RiskDecision:
    score: int
    priority: str
    category: str
    approval: str
    sla_minutes: int
    reasons: list[str]
    recommended_playbook: str


def _matches(text: str, terms: Iterable[str]) -> list[str]:
    lowered = (text or "").lower()
    return sorted(term for term in terms if term.lower() in lowered)


def score_event(event: dict) -> RiskDecision:
    """Score a normalized reputation event on a transparent 0-100 scale."""
    text = " ".join(str(event.get(k, "")) for k in ("title", "text", "excerpt"))
    source = event.get("source", "unknown")
    rating = event.get("rating")
    reach = max(0, int(event.get("estimated_reach") or 0))
    velocity = max(0.0, float(event.get("velocity") or 0))

    score = 5
    reasons = ["new reputation event"]
    crisis = _matches(text, CRISIS_TERMS)
    harassment = _matches(text, HARASSMENT_TERMS)
    operational = _matches(text, OPERATIONAL_TERMS)

    if rating is not None:
        if rating <= 1:
            score += 25
            reasons.append("one-star review")
        elif rating <= 2:
            score += 18
            reasons.append("low-rating review")
        elif rating >= 4:
            score -= 5
            reasons.append("positive review")
    if crisis:
        score += min(45, 20 + 5 * len(crisis))
        reasons.append("high-risk terms: " + ", ".join(crisis[:4]))
    if harassment:
        score += min(25, 10 + 4 * len(harassment))
        reasons.append("harassment indicators: " + ", ".join(harassment[:4]))
    if reach >= 100_000:
        score += 25
        reasons.append("very high estimated reach")
    elif reach >= 10_000:
        score += 15
        reasons.append("high estimated reach")
    elif reach >= 1_000:
        score += 8
        reasons.append("material estimated reach")
    if velocity >= 10:
        score += 20
        reasons.append("rapidly spreading")
    elif velocity >= 3:
        score += 10
        reasons.append("increasing velocity")
    if source in {"news", "broadcast", "legal", "regulator"}:
        score += 15
        reasons.append(f"high-authority source: {source}")

    score = max(0, min(100, score))
    if score >= 80:
        priority, approval, sla, playbook = "P0", "executive_legal", 15, "crisis"
    elif score >= 60:
        priority, approval, sla, playbook = "P1", "executive", 60, "rapid_response"
    elif score >= 35:
        priority, approval, sla, playbook = "P2", "manager", 240, "review_recovery"
    elif score >= 15:
        priority, approval, sla, playbook = "P3", "standard", 1440, "standard_response"
    else:
        priority, approval, sla, playbook = "P4", "auto_or_standard", 2880, "amplify_positive"

    if harassment:
        category = "harassment"
        playbook = "policy_violation"
        approval = "manager"
    elif crisis:
        category = "crisis_risk"
    elif operational and (rating is None or rating <= 3):
        category = "customer_experience"
    elif rating is not None and rating <= 2:
        category = "negative_review"
    elif rating is not None and rating >= 4:
        category = "positive_review"
    else:
        category = event.get("category") or "mention"

    return RiskDecision(score, priority, category, approval, sla, reasons, playbook)
