"""Route owned-media content by purpose and block cross-domain duplication."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


STREAM_SITE = {
    "canonical_depth": "GUYROFE_COM",
    "health_news": "DRGUYROFE_CO_IL",
    "evergreen_knowledge": "DRGUYROFE_COM",
    "media_archive": "GUYROFE_WIX_MEDIA_ARCHIVE",
}


def draft_metadata(path: str | Path) -> dict:
    """Read JSON-valued scheduling fields from the leading draft comment."""
    text = Path(path).read_text(encoding="utf-8")
    match = re.match(r"\A<!--\n(.*?)\n-->", text, flags=re.DOTALL)
    if not match:
        return {}
    result = {}
    for line in match.group(1).splitlines():
        if ": " not in line:
            continue
        key, raw = line.split(": ", 1)
        try:
            result[key] = json.loads(raw)
        except json.JSONDecodeError:
            result[key] = raw
    return result


def validate_stream_destination(
    *,
    site_key: str,
    stream: str | None,
    metadata: dict | None = None,
) -> None:
    if not stream:
        return
    expected = STREAM_SITE.get(stream)
    if not expected:
        raise ValueError(f"Unknown content stream: {stream}")
    if site_key != expected:
        raise ValueError(
            f"{stream} content belongs on {expected}, not {site_key}"
        )
    metadata = metadata or {}
    if stream == "media_archive":
        if not str(metadata.get("source_media_url") or "").startswith(
            ("https://", "http://")
        ):
            raise ValueError(
                "Media archive publication requires an original podcast or video URL"
            )
        if metadata.get("legacy_content_audit_passed") is not True:
            raise PermissionError(
                "Secondary Wix publication is locked until its legacy-content audit passes"
            )


def normalized_content(value: str) -> str:
    value = re.sub(r"\A<!--.*?-->\s*", "", value, flags=re.DOTALL)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\u0590-\u05FF]+", " ", value.lower(), flags=re.UNICODE)
    return " ".join(value.split())


def article_title(value: str) -> str:
    match = re.search(r"^#\s+(.+)$", value or "", flags=re.MULTILINE)
    return match.group(1).strip() if match else ""


def normalized_topic(value: str) -> str:
    value = re.sub(r"\|.*$", "", value or "")
    value = re.sub(r"ד[״\"]ר\s+גיא\s+רופא", " ", value)
    value = re.sub(r"[^\w\u0590-\u05FF]+", " ", value.lower(), flags=re.UNICODE)
    return " ".join(value.split())


def topic_is_duplicate(left: str, right: str) -> bool:
    """Detect the same editorial subject even when its wording is lightly changed."""
    a = normalized_topic(left)
    b = normalized_topic(right)
    if not a or not b:
        return False
    if a == b:
        return True
    left_tokens = set(a.split())
    right_tokens = set(b.split())
    smaller = min(len(left_tokens), len(right_tokens))
    if smaller < 2:
        return False
    return len(left_tokens & right_tokens) / smaller >= 0.75


def content_fingerprint(value: str) -> str:
    return hashlib.sha256(normalized_content(value).encode("utf-8")).hexdigest()


def _shingles(value: str, size: int = 5) -> set[tuple[str, ...]]:
    words = normalized_content(value).split()
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[index : index + size]) for index in range(len(words) - size + 1)}


def similarity(left: str, right: str) -> float:
    a = _shingles(left)
    b = _shingles(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def assert_cross_domain_original(
    *,
    content: str,
    site_key: str,
    draft_path: str | Path,
    draft_index_path: str | Path,
    project_root: str | Path,
    threshold: float = 0.82,
) -> str:
    """Reject reused topics and duplicate copy on every owned domain."""
    fingerprint = content_fingerprint(content)
    try:
        index = json.loads(Path(draft_index_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        index = {"drafts": []}
    root = Path(project_root)
    selected = Path(draft_path).resolve()
    indexed = list(index.get("drafts", []))
    known_paths = {str(item.get("path") or "") for item in indexed}
    for candidate in list(root.glob("content_drafts/*.md")) + list(root.glob("*.md")):
        relative = (
            candidate.relative_to(root).as_posix()
            if candidate.is_relative_to(root)
            else str(candidate)
        )
        if relative not in known_paths and str(candidate) not in known_paths:
            indexed.append({"path": relative})
    current_metadata = draft_metadata(selected) if selected.is_file() else {}
    current_topic = str(current_metadata.get("topic") or "")
    current_title = article_title(content)
    for item in indexed:
        other_site = item.get("destination_site_key") or "another owned site"
        other_path = Path(str(item.get("path") or ""))
        if not other_path.is_absolute():
            other_path = root / other_path
        try:
            if other_path.resolve() == selected or not other_path.is_file():
                continue
            other_content = other_path.read_text(encoding="utf-8")
        except OSError:
            continue
        other_metadata = draft_metadata(other_path)
        other_topic = str(item.get("topic") or other_metadata.get("topic") or "")
        other_title = article_title(other_content)
        if current_topic and other_topic and topic_is_duplicate(current_topic, other_topic):
            raise ValueError(
                f"Editorial topic was already used by {other_path.name}: {other_topic}"
            )
        if current_title and other_title and topic_is_duplicate(current_title, other_title):
            raise ValueError(
                f"Article title/topic was already used by {other_path.name}: {other_title}"
            )
        other_fingerprint = content_fingerprint(other_content)
        if other_fingerprint == fingerprint:
            raise ValueError(
                f"Exact duplicate already targets {other_site}: {other_path.name}"
            )
        score = similarity(content, other_content)
        if score >= threshold:
            raise ValueError(
                "Near-duplicate owned-media content blocked "
                f"({score:.2f} >= {threshold:.2f}) against {other_path.name}"
            )
    return fingerprint
