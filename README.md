# Reputation Command Center

An active reputation-management system for Dr. Guy Rofe. It continuously turns
monitor findings into explainable, auditable response workflows rather than
stopping at alerts.

## What it does now

- monitors search visibility, AI answers, reviews, web mentions and credential health;
- normalizes new findings into durable reputation events;
- assigns a transparent 0-100 risk score and P0-P4 priority;
- creates an SLA, approval policy and playbook task list;
- opens a crisis room for P0/P1 incidents;
- freezes scheduled publishing when a high-risk event is active;
- keeps a durable audit trail and exposes command-center metrics in the dashboard;
- replans an aggressive, evidence-led Google and AI visibility campaign every monitor cycle;
- maps first-page asset gaps and separates AI citations from explicit brand mentions;
- maintains a credential-free A/B/C/Q asset registry and excludes quarantined Web 2.0 mirrors from automation;
- treats `drguyrofe.com` as the official Wix knowledge-and-podcast hub, with a distinct job from the WordPress sites;
- declares every supported integration in `config/secrets_manifest.json` without storing credential values;
- continues the existing schema sync, social distribution and content workflows.

## Safety model

The system may automatically collect, classify, route and pause content. Public
responses, legal claims, medical claims, removals and crisis statements require
the approval level attached to the event. Playbooks explicitly record prohibited
actions such as exposing patient data, promising removal, retaliation, review
incentives or speculative crisis responses.

## Operator commands

```bash
python scripts/command_center.py status
python scripts/command_center.py ingest --source google --rating 1 --text "review text"
python scripts/command_center.py complete-task TASK_ID --actor NAME
python scripts/command_center.py add-fact CRISIS_ROOM_ID "Verified fact" --source-url URL
python scripts/command_center.py resolve-event EVENT_ID --resolution "resolution notes"
python scripts/command_center.py set-freeze off --actor NAME
python scripts/command_center.py plan-growth
python scripts/check_secrets.py
```

`check_secrets.py` reports missing environment-variable names only. GitHub
Secrets must contain platform-issued API keys, OAuth tokens, application
passwords or site identifiers—never personal passwords copied from an asset
inventory. Wix publishing for `drguyrofe.com` requires both
`WIX_DRGUYROFE_COM_API` and `WIX_DRGUYROFE_COM_SITE_ID`.

Content freeze cannot be removed while an active crisis room exists.

## Automated workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| Reputation Monitor | Every 2 hours | Detect, route, persist and report reputation events |
| Content Publisher | Mon/Wed/Fri | Generate and publish long-form content when not frozen |
| Social Distribution | Mon/Wed/Fri | Distribute approved content when not frozen |
| Schema Sync | Weekly | Keep connected site facts and structured data aligned |

## Validation

```bash
python -m unittest discover -s tests -v
python -m compileall -q scripts tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data model, routing
rules, governance boundaries and planned premium layers.
