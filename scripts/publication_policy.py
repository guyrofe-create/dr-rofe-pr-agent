"""Owner-level rules that every public publication must satisfy."""

import re

CONSULTATION_INVITATIONS = (
    'לייעוץ עם ד"ר גיא רופא',
    "לייעוץ עם ד״ר גיא רופא",
    "פנו אליי",
    "פני אליי",
    "צרו קשר",
    "צרי קשר",
    "קבעו תור",
    "קבעי תור",
    "אני כאן כדי לעזור",
    "אני מזמין",
    "אני מזמינה",
    "ייעוץ אישי",
    "ייעוץ מקצועי",
    "דברו איתי",
    "דברי איתי",
    "שלחו הודעה",
    "שלחי הודעה",
    "לתיאום",
    "לקביעת",
    "contact me",
    "book an appointment",
    "schedule a consultation",
)

ACTIVE_PRACTICE_CLAIMS = (
    "המטופלות שלי",
    "במרפאה שלי",
    "אני מטפל",
    "אני מנתח",
    "זמינות ישירה לרופא",
    "ליווי אישי",
)


def enforce_publication_policy(text):
    """Reject solicitation and active-practice claims in every public channel."""
    content = (text or "").strip()
    folded = content.casefold()
    violations = [
        phrase
        for phrase in (*CONSULTATION_INVITATIONS, *ACTIVE_PRACTICE_CLAIMS)
        if phrase.casefold() in folded
    ]
    # Catch common variants that add punctuation or a pronoun between the words.
    if re.search(r"(?:קבע|קבעי|קבעו).{0,12}(?:תור|פגישה|ייעוץ)", content):
        violations.append("appointment invitation")
    if violations:
        raise ValueError(
            "publication violates owner publication policy: " + ", ".join(violations)
        )
    return content


CTA_PROMPT = (
    "אין להזמין לייעוץ, לקביעת תור, ליצירת קשר או לפנייה לד״ר גיא רופא. "
    "אין להציג אותו כרופא מטפל פעיל, כמנתח פעיל או כבעל מרפאה פעילה. "
    "אם מופיעה קריאה לפעולה, היא תהיה רק: למידע נוסף: https://guyrofe.com"
)
