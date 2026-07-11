# Reputation Command Center architecture

## Operating loop

`Listen -> Understand -> Score -> Route -> Approve -> Act -> Measure -> Learn`

The initial release implements the deterministic center of this loop. Existing
monitors remain collectors. Their alerts and new mentions are ingested by
`CommandCenter`, deduplicated, scored, assigned a playbook, persisted and shown
on the public dashboard.

## Core records

### Reputation event

Every event has a stable hash ID, source, timestamps, category, score, P0-P4
priority, SLA, approval requirement, reasons, playbook and lifecycle status.
Repeated observations increment `occurrences` rather than creating alert spam.

### Task

Playbook steps become tasks tied to the event. Each task inherits the event's
approval level, SLA and prohibited-action list.

### Crisis room

P0/P1 events open a crisis room with a fact timeline, claims, unknowns,
audiences, approvers and holding-statement slot. Opening a crisis room freezes
scheduled content. The freeze cannot be removed until all crisis rooms close.

### Audit entry

Every ingest, repeat observation, task completion, crisis action and freeze
change is recorded with timestamp, actor, target and details.

## Risk routing

The initial risk engine is deterministic and explainable. It combines rating,
high-risk language, harassment indicators, source authority, estimated reach
and velocity. An LLM may later enrich classification, but it must never silently
override safety routing.

| Priority | Score | Default SLA | Approval |
|---|---:|---:|---|
| P0 | 80-100 | 15 minutes | Executive + legal |
| P1 | 60-79 | 60 minutes | Executive |
| P2 | 35-59 | 4 hours | Manager |
| P3 | 15-34 | 24 hours | Standard |
| P4 | 0-14 | 48 hours | Auto or standard |

## Governance invariants

- Never disclose patient/customer private information in a public response.
- Never incentivize a positive review or condition outreach on sentiment.
- Never promise removal of a platform review.
- Never mass-report, retaliate, threaten or manufacture endorsements.
- Never auto-publish legal, medical or crisis claims.
- Preserve evidence before reporting or requesting removal.
- Keep facts, claims and unknowns separated in crisis work.

## Next premium layers

1. Authenticated multi-tenant API, encrypted connector vault and role-based approvals.
2. Unified inbox for review, social, news, forum, email and CRM events.
3. Contextual response drafting with privacy and policy validation.
4. Review-request journeys without review gating or incentives.
5. Narrative map and entity knowledge graph for search and AI consistency.
6. Root-cause analysis that turns recurring complaints into operational tasks.
7. Broader AI-answer measurement with prompts, citations, geography and model versions.
8. Outcome analytics: response time, resolution, sentiment recovery, leads and revenue.
