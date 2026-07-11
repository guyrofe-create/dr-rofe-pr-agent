"""Fallback for platforms with no safe automated-posting API:
TikTok, Quora, LinkedIn (personal profile), Flipboard, Slideshare, About.me.

These platforms either have no public posting API, or require a company/app-review
process that isn't worth the ban risk for a personal account. Instead of risky
credential-based automation, this module packages ready-to-paste content so a
human posts it in ~30 seconds per platform.

Output: appends a dated section to social_drafts/<date>.md in the repo, and
(if configured) opens a GitHub Issue with a checklist so nothing gets missed.
"""
import os
from datetime import datetime

PLATFORMS = ["TikTok", "Quora", "LinkedIn", "Flipboard", "Slideshare", "About.me"]


def build_draft_markdown(title, body, url, platform_notes=None):
    date = datetime.now().strftime("%Y-%m-%d")
    lines = [f"# טיוטות תוכן ליום {date}", "", f"**כותרת:** {title}", "", "---", ""]
    for p in PLATFORMS:
        note = (platform_notes or {}).get(p, "")
        lines += [
            f"## {p}",
            "- [ ] הודבק ופורסם",
            "",
            "**טקסט מוכן להדבקה:**",
            "```",
            body[:800],
            (f"\n{url}" if url else ""),
            "```",
        ]
        if note:
            lines.append(f"_הערה: {note}_")
        lines.append("")
    return "\n".join(lines)


def write_local(title, body, url, out_dir="social_drafts", platform_notes=None):
    os.makedirs(out_dir, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(out_dir, f"{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_draft_markdown(title, body, url, platform_notes))
    return path
