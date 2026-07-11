"""Persistent Reputation Command Center state and orchestration."""
from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from .playbooks import get_playbook
from .risk import score_event


DEFAULT_STATE = {
    "version": 1,
    "updated_at": None,
    "content_freeze": False,
    "events": [],
    "tasks": [],
    "crisis_rooms": [],
    "audit_log": [],
    "metrics": {},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CommandCenter:
    def __init__(self, path: str):
        self.path = path
        self.state = self._load()

    def _load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            return {**deepcopy(DEFAULT_STATE), **loaded}
        except (OSError, ValueError, TypeError):
            return deepcopy(DEFAULT_STATE)

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.state["updated_at"] = _iso(_now())
        self._recalculate_metrics()
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(self.state, handle, ensure_ascii=False, indent=2)

    @staticmethod
    def event_id(event: dict) -> str:
        identity = "|".join(str(event.get(k, "")) for k in ("source", "external_id", "url", "author", "text", "title"))
        return "evt_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]

    def ingest(self, raw_event: dict) -> tuple[dict, bool]:
        event = deepcopy(raw_event)
        event["id"] = event.get("id") or self.event_id(event)
        existing = next((item for item in self.state["events"] if item["id"] == event["id"]), None)
        if existing:
            existing["last_seen_at"] = _iso(_now())
            existing["occurrences"] = existing.get("occurrences", 1) + 1
            self._audit("event_seen_again", existing["id"], {"occurrences": existing["occurrences"]})
            return existing, False

        decision = score_event(event)
        created = _now()
        normalized = {
            **event,
            "status": "new",
            "created_at": event.get("created_at") or _iso(created),
            "last_seen_at": _iso(created),
            "occurrences": 1,
            "risk_score": decision.score,
            "priority": decision.priority,
            "category": decision.category,
            "approval_required": decision.approval,
            "sla_due_at": _iso(created + timedelta(minutes=decision.sla_minutes)),
            "risk_reasons": decision.reasons,
            "playbook": decision.recommended_playbook,
        }
        self.state["events"].append(normalized)
        self._create_tasks(normalized)
        plan = get_playbook(normalized["playbook"])
        if plan.get("freeze_scheduled_content"):
            self.state["content_freeze"] = True
        if normalized["priority"] in {"P0", "P1"}:
            self._open_crisis_room(normalized)
        self._audit("event_ingested", normalized["id"], {"priority": normalized["priority"], "score": normalized["risk_score"]})
        return normalized, True

    def ingest_monitor_report(self, report: dict) -> list[dict]:
        created = []
        for alert in report.get("alerts", []):
            event, is_new = self.ingest({
                "source": alert.get("source", "monitor"),
                "external_id": f"{report.get('date')}|{alert.get('type')}|{alert.get('author', '')}",
                "title": alert.get("type", "monitor alert"),
                "text": alert.get("excerpt", ""),
                "rating": alert.get("rating"),
                "category": alert.get("type"),
                "metadata": alert,
            })
            if is_new:
                created.append(event)
        for mention in (report.get("web_mentions") or {}).get("new_mentions", []):
            event, is_new = self.ingest({
                "source": "web",
                "url": mention.get("link"),
                "title": mention.get("title", "New web mention"),
                "text": mention.get("title", ""),
                "category": "web_mention",
            })
            if is_new:
                created.append(event)
        return created

    def _create_tasks(self, event: dict) -> None:
        playbook = get_playbook(event["playbook"])
        for index, step in enumerate(playbook["steps"], start=1):
            self.state["tasks"].append({
                "id": f"tsk_{event['id'][4:]}_{index}",
                "event_id": event["id"],
                "title": step,
                "status": "pending",
                "approval_required": event["approval_required"],
                "created_at": _iso(_now()),
                "due_at": event["sla_due_at"],
                "prohibited_actions": playbook.get("prohibited", []),
            })

    def _open_crisis_room(self, event: dict) -> None:
        room = {
            "id": "crm_" + event["id"][4:],
            "event_id": event["id"],
            "status": "active",
            "opened_at": _iso(_now()),
            "fact_timeline": [],
            "claims": [],
            "unknowns": [],
            "audiences": [],
            "approvers": ["executive", "communications", "legal"],
            "holding_statement": None,
        }
        self.state["crisis_rooms"].append(room)
        self._audit("crisis_room_opened", room["id"], {"event_id": event["id"]})

    def _audit(self, action: str, object_id: str, details: dict | None = None) -> None:
        self.state["audit_log"].append({
            "at": _iso(_now()), "actor": "reputation-agent", "action": action,
            "object_id": object_id, "details": details or {},
        })
        self.state["audit_log"] = self.state["audit_log"][-1000:]

    def _recalculate_metrics(self) -> None:
        open_events = [e for e in self.state["events"] if e.get("status") not in {"closed", "resolved"}]
        self.state["metrics"] = {
            "open_events": len(open_events),
            "critical_events": sum(e.get("priority") in {"P0", "P1"} for e in open_events),
            "pending_tasks": sum(t.get("status") == "pending" for t in self.state["tasks"]),
            "active_crises": sum(r.get("status") == "active" for r in self.state["crisis_rooms"]),
            "content_freeze": self.state["content_freeze"],
        }

    def public_snapshot(self) -> dict:
        """Return a dashboard-safe view without private customer data."""
        snapshot = deepcopy(self.state)
        for event in snapshot["events"]:
            event.pop("metadata", None)
            if event.get("category") in {"negative_review", "customer_experience"}:
                event["text"] = (event.get("text") or "")[:180]
        return snapshot
