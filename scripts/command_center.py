#!/usr/bin/env python3
"""Operator CLI for the Reputation Command Center.

Examples:
  python scripts/command_center.py status
  python scripts/command_center.py ingest --source google --rating 1 --text "..."
  python scripts/command_center.py complete-task tsk_...
  python scripts/command_center.py resolve-event evt_...
  python scripts/command_center.py add-fact crm_... "Verified fact"
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

from reputation_core import CommandCenter, plan_growth_campaign

ROOT = os.path.join(os.path.dirname(__file__), "..")
STATE_PATH = os.path.join(ROOT, "data", "command_center.json")
PROFILE_PATH = os.path.join(ROOT, "data", "business_profile.json")
OBSERVATIONS_PATH = os.path.join(ROOT, "data", "growth_observations.json")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find(items, object_id):
    return next((item for item in items if item.get("id") == object_id), None)


def status(center):
    center._recalculate_metrics()
    print(json.dumps(center.state["metrics"], ensure_ascii=False, indent=2))
    for event in sorted(center.state["events"], key=lambda e: (e.get("priority", "P9"), e.get("created_at", ""))):
        if event.get("status") not in {"resolved", "closed"}:
            print(f"{event['priority']} {event['id']} score={event['risk_score']} {event['category']} [{event['status']}]")


def main():
    parser = argparse.ArgumentParser(description="Reputation Command Center operator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--source", required=True)
    ingest.add_argument("--text", required=True)
    ingest.add_argument("--title", default="Manual reputation event")
    ingest.add_argument("--rating", type=int)
    ingest.add_argument("--url")
    ingest.add_argument("--reach", type=int, default=0)
    ingest.add_argument("--velocity", type=float, default=0)

    complete = sub.add_parser("complete-task")
    complete.add_argument("task_id")
    complete.add_argument("--actor", default="operator")

    resolve = sub.add_parser("resolve-event")
    resolve.add_argument("event_id")
    resolve.add_argument("--actor", default="operator")
    resolve.add_argument("--resolution", default="resolved")

    fact = sub.add_parser("add-fact")
    fact.add_argument("room_id")
    fact.add_argument("fact")
    fact.add_argument("--source-url")
    fact.add_argument("--actor", default="operator")

    freeze = sub.add_parser("set-freeze")
    freeze.add_argument("value", choices=["on", "off"])
    freeze.add_argument("--actor", default="operator")

    growth = sub.add_parser("plan-growth")
    growth.add_argument("--profile", default=PROFILE_PATH)
    growth.add_argument("--observations", default=OBSERVATIONS_PATH)

    args = parser.parse_args()
    center = CommandCenter(STATE_PATH)

    if args.command == "status":
        status(center)
        return
    if args.command == "ingest":
        event, created = center.ingest({
            "source": args.source, "title": args.title, "text": args.text,
            "rating": args.rating, "url": args.url,
            "estimated_reach": args.reach, "velocity": args.velocity,
            "external_id": f"manual|{now_iso()}|{args.source}",
        })
        center.save()
        print(json.dumps({"created": created, "event": event}, ensure_ascii=False, indent=2))
        return
    if args.command == "plan-growth":
        with open(args.profile, encoding="utf-8") as handle:
            profile = json.load(handle)
        with open(args.observations, encoding="utf-8") as handle:
            observations = json.load(handle)
        campaign = plan_growth_campaign(profile, observations)
        center.state["campaigns"] = [c for c in center.state["campaigns"] if c.get("id") != campaign["id"]]
        center.state["campaigns"].append(campaign)
        center.state["serp_assets"] = observations.get("serp_assets", [])
        center._audit("growth_campaign_planned", campaign["id"], {"tasks": len(campaign["tasks"])})
        center.save()
        print(json.dumps(campaign, ensure_ascii=False, indent=2))
        return
    if args.command == "complete-task":
        task = find(center.state["tasks"], args.task_id)
        if not task:
            sys.exit(f"Task not found: {args.task_id}")
        task.update({"status": "completed", "completed_at": now_iso(), "completed_by": args.actor})
        center._audit("task_completed", task["id"], {"actor": args.actor})
    elif args.command == "resolve-event":
        event = find(center.state["events"], args.event_id)
        if not event:
            sys.exit(f"Event not found: {args.event_id}")
        event.update({"status": "resolved", "resolved_at": now_iso(), "resolution": args.resolution})
        for task in center.state["tasks"]:
            if task.get("event_id") == event["id"] and task.get("status") == "pending":
                task["status"] = "cancelled"
        for room in center.state["crisis_rooms"]:
            if room.get("event_id") == event["id"]:
                room.update({"status": "closed", "closed_at": now_iso()})
        center._audit("event_resolved", event["id"], {"actor": args.actor, "resolution": args.resolution})
    elif args.command == "add-fact":
        room = find(center.state["crisis_rooms"], args.room_id)
        if not room:
            sys.exit(f"Crisis room not found: {args.room_id}")
        room["fact_timeline"].append({"at": now_iso(), "fact": args.fact, "source_url": args.source_url, "added_by": args.actor})
        center._audit("crisis_fact_added", room["id"], {"actor": args.actor})
    elif args.command == "set-freeze":
        if args.value == "off" and any(r.get("status") == "active" for r in center.state["crisis_rooms"]):
            sys.exit("Cannot remove content freeze while an active crisis room exists")
        center.state["content_freeze"] = args.value == "on"
        center._audit("content_freeze_changed", "global", {"actor": args.actor, "value": args.value})

    center.save()
    status(center)


if __name__ == "__main__":
    main()
