"""Owner-level rules that every public publication must satisfy."""

import re

from reputation_core.strategy import (
    content_generation_prompt,
    ensure_product_channel_allowed,
    load_client_profile,
    load_strategy,
)

_CLIENT = load_client_profile()
_CLIENT_FACTS = _CLIENT["canonical_facts"]
_CLIENT_NAME = _CLIENT_FACTS["primary_name"]

_GUARDRAILS = _CLIENT.get("publication_guardrails", {})
CONSULTATION_INVITATIONS = tuple(
    _GUARDRAILS.get("prohibited_solicitation_phrases", [])
)
ACTIVE_PRACTICE_CLAIMS = tuple(
    _GUARDRAILS.get("prohibited_current_status_phrases", [])
)


def enforce_publication_policy(text):
    """Reject solicitation and active-practice claims in every public channel."""
    content = (text or "").strip()
    folded = content.casefold()
    # Accurate non-practicing disclosures are allowed and must not be mistaken
    # for the affirmative phrases they negate.
    folded = re.sub(
        r"(?:אינו|אינה|אינם|אינן|לא)\s+"
        r"(?:מקבל(?:ת|ים|ות)?(?:\s+כיום)?\s+מטופל(?:ים|ות)|"
        r"מפעיל(?:ה)?\s+מרפאה|מעניק(?:ה)?\s+טיפול|"
        r"זמין(?:ה)?\s+לקביעת\s+תורים?)",
        "",
        folded,
    )
    folded = re.sub(
        r"(?:not|is not|does not)\s+"
        r"(?:currently\s+)?(?:accepting patients|operate a clinic|"
        r"available for appointments)",
        "",
        folded,
    )
    violations = [
        phrase
        for phrase in (*CONSULTATION_INVITATIONS, *ACTIVE_PRACTICE_CLAIMS)
        if phrase.casefold() in folded
    ]
    # Catch common variants that add punctuation or a pronoun between the words.
    if ACTIVE_PRACTICE_CLAIMS and re.search(
        r"(?:קבע|קבעי|קבעו).{0,12}(?:תור|פגישה|ייעוץ)", content
    ):
        violations.append("appointment invitation")
    if violations:
        raise ValueError(
            "publication violates owner publication policy: " + ", ".join(violations)
        )
    return content


_STRATEGY = load_strategy()
CTA_PROMPT = (
    f"אין להזמין לייעוץ, לקביעת תור, ליצירת קשר או לפנייה ל{_CLIENT_NAME}. "
    "אין להציג את הלקוח כבעל פעילות מקצועית נוכחית הסותרת את מאגר העובדות. "
    "אם מופיעה קריאה לפעולה, היא תהיה רק: "
    f"{_STRATEGY['canonical_facts']['allowed_cta_he']}"
)

REPUTATION_KNOWLEDGE_PROMPT = content_generation_prompt()


def enforce_channel_policy(channel):
    """Block product publication to owner-managed or disabled channels."""
    ensure_product_channel_allowed(channel)
    return channel
