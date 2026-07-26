"""Owner-level rules that every public publication must satisfy."""

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
)


def enforce_publication_policy(text):
    """Reject owner-solicitation CTAs while allowing general medical guidance."""
    content = (text or "").strip()
    violations = [phrase for phrase in CONSULTATION_INVITATIONS if phrase in content]
    if violations:
        raise ValueError(
            "publication invites consultation or contact: " + ", ".join(violations)
        )
    return content


CTA_PROMPT = (
    "אין להזמין לייעוץ, לקביעת תור, ליצירת קשר או לפנייה לד״ר גיא רופא. "
    "אם מופיעה קריאה לפעולה, היא תהיה רק: למידע נוסף: guyrofe.com"
)
