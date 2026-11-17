"""Durable, append-only editorial topic memory.

The short dashboard indexes are presentation caches and are intentionally
bounded.  Topic uniqueness must never depend on those caches or on retained
draft files, so this ledger records every attempted topic and its lifecycle.
"""
from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def normalize_topic(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("״", '"').replace("׳", "'")
    text = re.sub(r"[^\w\s\u0590-\u05ff]", " ", text.lower())
    return " ".join(text.split())


def topic_id(topic: str) -> str:
    normalized = normalize_topic(topic)
    return "topic_" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def load_topic_ledger(path: str | Path) -> dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        payload = {"version": 1, "topics": []}
    if not isinstance(payload.get("topics"), list):
        payload["topics"] = []
    payload["version"] = 1
    return payload


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write(rendered)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def record_topic_event(
    path: str | Path,
    *,
    topic: str,
    status: str,
    occurred_at: str | None = None,
    title: str | None = None,
    stream: str | None = None,
    draft_path: str | None = None,
    approval_id: str | None = None,
    campaign_status: str | None = None,
    urls: list[str] | None = None,
    source: str | None = None,
) -> dict:
    """Upsert one topic and append one deduplicated lifecycle event."""
    topic = " ".join(str(topic or "").split())
    if not topic:
        raise ValueError("Topic ledger event requires a non-empty topic")
    occurred_at = occurred_at or datetime.now(timezone.utc).isoformat()
    ledger_path = Path(path)
    payload = load_topic_ledger(ledger_path)
    identifier = topic_id(topic)
    entry = next(
        (item for item in payload["topics"] if item.get("topic_id") == identifier),
        None,
    )
    if entry is None:
        entry = {
            "topic_id": identifier,
            "topic": topic,
            "normalized_topic": normalize_topic(topic),
            "first_seen_at": occurred_at,
            "last_seen_at": occurred_at,
            "titles": [],
            "streams": [],
            "events": [],
        }
        payload["topics"].append(entry)
    entry["last_seen_at"] = max(str(entry.get("last_seen_at") or ""), occurred_at)
    if title and title not in entry["titles"]:
        entry["titles"].append(title)
    if stream and stream not in entry["streams"]:
        entry["streams"].append(stream)
    event = {
        "status": status,
        "occurred_at": occurred_at,
        **({"source": source} if source else {}),
        **({"stream": stream} if stream else {}),
        **({"draft_path": draft_path} if draft_path else {}),
        **({"approval_id": approval_id} if approval_id else {}),
        **({"campaign_status": campaign_status} if campaign_status else {}),
        **({"urls": sorted(set(urls or []))} if urls else {}),
    }
    identity = (
        event.get("status"), event.get("source"), event.get("draft_path"),
        event.get("approval_id"), event.get("campaign_status"),
        tuple(event.get("urls") or []),
    )
    existing_identities = {
        (
            item.get("status"), item.get("source"), item.get("draft_path"),
            item.get("approval_id"), item.get("campaign_status"),
            tuple(item.get("urls") or []),
        )
        for item in entry["events"]
    }
    if identity not in existing_identities:
        entry["events"].append(event)
        entry["events"].sort(key=lambda item: item.get("occurred_at", ""))
    payload["topics"].sort(key=lambda item: item.get("first_seen_at", ""))
    _write_atomic(ledger_path, payload)
    return entry


def ledger_topic_values(path: str | Path) -> list[str]:
    values: list[str] = []
    for item in load_topic_ledger(path).get("topics", []):
        values.append(str(item.get("topic") or ""))
        values.extend(str(title or "") for title in item.get("titles", []))
    return list(dict.fromkeys(value for value in values if value.strip()))


def _draft_metadata(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    topic_match = re.search(r"^topic:\s*(.+)$", text, flags=re.MULTILINE)
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    generated_match = re.search(r"^generated_at:\s*(.+)$", text, flags=re.MULTILINE)
    stream_match = re.search(r"^content_stream:\s*(.+)$", text, flags=re.MULTILINE)

    def clean(match):
        if not match:
            return None
        raw = match.group(1).strip()
        try:
            return str(json.loads(raw))
        except json.JSONDecodeError:
            return raw

    return {
        "topic": clean(topic_match),
        "title": clean(title_match),
        "generated_at": clean(generated_match),
        "stream": clean(stream_match),
    }


def sync_repository_topics(project_root: str | Path, ledger_path: str | Path) -> dict:
    """Backfill and advance the ledger from every durable repository artifact."""
    root = Path(project_root)
    ledger_path = Path(ledger_path)
    draft_topics: dict[str, dict] = {}
    for draft in sorted((root / "content_drafts").glob("*.md")):
        metadata = _draft_metadata(draft)
        if not metadata.get("topic"):
            continue
        relative = draft.relative_to(root).as_posix()
        draft_topics[relative] = metadata
        record_topic_event(
            ledger_path,
            topic=metadata["topic"],
            title=metadata.get("title"),
            stream=metadata.get("stream"),
            draft_path=relative,
            status="draft_ready",
            occurred_at=metadata.get("generated_at") or datetime.now(timezone.utc).isoformat(),
            source="draft",
        )

    approval_index = root / "approval_bundles" / "index.json"
    try:
        approvals = json.loads(approval_index.read_text(encoding="utf-8")).get("bundles", [])
    except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
        approvals = []
    for approval in approvals:
        draft_path = approval.get("draft_path")
        metadata = draft_topics.get(str(draft_path))
        if not metadata:
            continue
        record_topic_event(
            ledger_path,
            topic=metadata["topic"],
            title=metadata.get("title"),
            stream=metadata.get("stream"),
            draft_path=draft_path,
            approval_id=approval.get("approval_id"),
            status=str(approval.get("status") or "approval_bundle_created"),
            occurred_at=approval.get("created_at") or metadata.get("generated_at"),
            source="approval_bundle",
        )

    for campaign_path in sorted((root / "content_drafts" / "campaigns").glob("*.json")):
        if campaign_path.name == "index.json":
            continue
        try:
            campaign = json.loads(campaign_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, TypeError):
            continue
        draft_path = campaign.get("draft")
        metadata = draft_topics.get(str(draft_path))
        if not metadata:
            continue
        destinations = campaign.get("destinations") or []
        urls = [
            item["url"] for item in destinations
            if item.get("url") and item.get("status") in {"published", "verified"}
        ]
        record_topic_event(
            ledger_path,
            topic=metadata["topic"],
            title=campaign.get("title") or metadata.get("title"),
            stream=metadata.get("stream"),
            draft_path=draft_path,
            approval_id=campaign.get("approval_id"),
            campaign_status=campaign.get("status"),
            urls=urls,
            status=("published" if urls else "publication_attempted"),
            occurred_at=campaign.get("published_at") or metadata.get("generated_at"),
            source="campaign",
        )
    return load_topic_ledger(ledger_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--ledger", type=Path)
    args = parser.parse_args()
    ledger = args.ledger or args.root / "data" / "content_topic_ledger.json"
    payload = sync_repository_topics(args.root, ledger)
    print(json.dumps({"topics": len(payload["topics"]), "ledger": str(ledger)}))


if __name__ == "__main__":
    main()
