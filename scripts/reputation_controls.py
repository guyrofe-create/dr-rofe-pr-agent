#!/usr/bin/env python3
"""Prepare evidence-first reputation controls without external submission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from reputation_core import (
    audit_backlinks,
    build_ai_feedback_task,
    build_disavow_proposal,
    build_knowledge_panel_task,
    build_review_request_campaign,
    build_wikimedia_workstream,
    validate_legal_evidence_chain,
)


def load(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare reputation controls; never performs external writes"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backlinks = sub.add_parser("audit-backlinks")
    backlinks.add_argument("current")
    backlinks.add_argument("--previous")
    backlinks.add_argument("--owned-host", action="append", default=[])

    disavow = sub.add_parser("propose-disavow")
    disavow.add_argument("audit")
    disavow.add_argument("domains", nargs="+")

    reviews = sub.add_parser("prepare-review-campaign")
    reviews.add_argument("recipients")
    reviews.add_argument("--destination-url", required=True)
    reviews.add_argument("--message", required=True)

    legal = sub.add_parser("verify-legal-evidence")
    legal.add_argument("record")
    legal.add_argument("--document")

    knowledge = sub.add_parser("knowledge-panel-task")
    knowledge.add_argument("entity")

    feedback = sub.add_parser("ai-feedback-task")
    feedback.add_argument("sample")

    wikimedia = sub.add_parser("wikimedia-workstream")
    wikimedia.add_argument("entity")

    args = parser.parse_args()
    if args.command == "audit-backlinks":
        result = audit_backlinks(
            load(args.current),
            load(args.previous) if args.previous else [],
            owned_hosts=set(args.owned_host),
        )
    elif args.command == "propose-disavow":
        result = build_disavow_proposal(load(args.audit), args.domains)
    elif args.command == "prepare-review-campaign":
        result = build_review_request_campaign(
            load(args.recipients),
            destination_url=args.destination_url,
            message=args.message,
        )
    elif args.command == "verify-legal-evidence":
        payload = Path(args.document).read_bytes() if args.document else None
        result = validate_legal_evidence_chain(load(args.record), document_bytes=payload)
    elif args.command == "knowledge-panel-task":
        result = build_knowledge_panel_task(load(args.entity))
    elif args.command == "ai-feedback-task":
        result = build_ai_feedback_task(load(args.sample))
    else:
        result = build_wikimedia_workstream(load(args.entity))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
