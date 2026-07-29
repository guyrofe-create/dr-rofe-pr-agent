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
    """Reject exact and near-duplicate drafts assigned to another owned domain."""
    fingerprint = content_fingerprint(content)
    try:
        index = json.loads(Path(draft_index_path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return fingerprint
    root = Path(project_root)
    selected = Path(draft_path).resolve()
    for item in index.get("drafts", []):
        other_site = item.get("destination_site_key")
        if not other_site or other_site == site_key:
            continue
        other_path = Path(str(item.get("path") or ""))
        if not other_path.is_absolute():
            other_path = root / other_path
        try:
            if other_path.resolve() == selected or not other_path.is_file():
                continue
            other_content = other_path.read_text(encoding="utf-8")
        except OSError:
            continue
        other_fingerprint = content_fingerprint(other_content)
        if other_fingerprint == fingerprint:
            raise ValueError(
                f"Exact cross-domain duplicate already targets {other_site}: {other_path.name}"
            )
        score = similarity(content, other_content)
        if score >= threshold:
            raise ValueError(
                "Near-duplicate cross-domain content blocked "
                f"({score:.2f} >= {threshold:.2f}) against {other_path.name}"
            )
    return fingerprint
