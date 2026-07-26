"""Authorized Bing Webmaster Tools AI Performance export adapter."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


ALIASES = {
    "date": {"date", "day"},
    "cited_url": {
        "cited_url", "url", "page", "cited page", "cited_page",
    },
    "grounding_query": {
        "grounding_query", "grounding query", "query", "query phrase",
    },
    "citations": {
        "citations", "citation count", "citation_count", "total citations",
    },
    "intent": {"intent", "intents"},
    "topic": {"topic", "topics"},
    "citation_share": {
        "citation_share", "citation share", "share",
    },
}


def _canonical_header(header: str) -> str | None:
    normalized = " ".join((header or "").strip().lower().split())
    return next(
        (field for field, aliases in ALIASES.items() if normalized in aliases),
        None,
    )


def _number(value, *, integer: bool = False):
    if value in (None, ""):
        return 0 if integer else None
    normalized = str(value).strip().replace(",", "").replace("%", "")
    parsed = float(normalized)
    if "%" in str(value):
        parsed /= 100
    return int(parsed) if integer else parsed


def _normalize_row(row: dict) -> dict:
    normalized = {}
    for header, value in row.items():
        field = _canonical_header(header)
        if field:
            normalized[field] = value.strip() if isinstance(value, str) else value
    normalized["citations"] = _number(
        normalized.get("citations"), integer=True
    )
    if normalized.get("citation_share") not in (None, ""):
        normalized["citation_share"] = _number(
            normalized["citation_share"]
        )
    return normalized


def import_bing_ai_performance(path: Path) -> dict:
    """Normalize a customer-authorized CSV or JSON export."""
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_rows = payload if isinstance(payload, list) else payload.get(
            "rows", []
        )
    else:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            source_rows = list(csv.DictReader(handle))
    rows = [_normalize_row(row) for row in source_rows]
    rows = [
        row for row in rows
        if row.get("cited_url") or row.get("grounding_query")
    ]
    dates = sorted({row.get("date") for row in rows if row.get("date")})
    return {
        "version": 1,
        "engine": "Bing",
        "surface": "ai_performance",
        "interface": "bing_webmaster_tools_consumer_ui",
        "collection_method": "authorized_manual_export",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": path.name,
        "period": {
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None,
        },
        "rows": rows,
    }
