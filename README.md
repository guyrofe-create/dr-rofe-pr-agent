# Reputation Command Center

A configurable single-client reputation-management product. Each installation
serves one client and loads that client's identity, search goals, facts,
channels and approval rules from `config/client_profile.json`. The current
repository contains the Dr. Guy Rofe pilot profile.

## What it does now

- monitors search visibility, AI answers, reviews, web mentions and credential health;
- fails closed when a SERP run is partial or an AI answer is not supported by
  the approved fact registry;
- retries a daily SERP measurement after provider errors instead of recording
  the failed attempt as a completed daily measurement;
- gates new controlled assets by distinct purpose, content runway, maintenance
  capacity, portfolio health and a rolling volume budget;
- normalizes new findings into durable reputation events;
- assigns a transparent 0-100 risk score and P0-P4 priority;
- creates an SLA, approval policy and playbook task list;
- opens a crisis room for P0/P1 incidents;
- freezes scheduled publishing when a high-risk event is active;
- keeps a durable audit trail and exposes command-center metrics in the dashboard;
- replans an aggressive, evidence-led Google and AI visibility campaign every monitor cycle;
- records the complete top ten for every approved brand-name variant, locale and device;
- classifies desired, controlled and negative SERP positions instead of treating
  asset existence as visibility;
- ingests 28-day Search Console query/page evidence through the existing shared
  Google OAuth connection and converts striking-distance pages into work;
- rejects thin new-property ideas through a distinct-purpose, maintenance and
  authority decision gate;
- loads `config/reputation_strategy.json` as the enforceable source for canonical
  facts, channel ownership, content evidence rules, AI monitoring and success metrics;
- samples each approved AI reputation prompt three times per day and opens a
  correction workflow only when the majority indicates the same problem;
- requires medical article drafts to include at least two direct authoritative sources;
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

## Single-tenant installation wizard

Every deployment contains exactly one customer profile and one customer data
set. Create a new isolated installation from a customer-owned specification:

```bash
python scripts/install_client.py \
  --spec config/client_install_spec.example.json \
  --destination /path/to/customer-installation
```

The wizard creates the profile, approved-fact registry, asset registry, SERP
targets, campaign plan and a manifest containing required secret **names**.
Secret values are never written. A deployment can point the same engine at its
isolated files with `REPUTATION_INSTALLATION_ROOT`.

Coverage expansion is capacity-derived, not based on a universal posting or
asset quota. The engine automatically stops expansion on duplicate intent,
cross-domain duplication, cannibalization, thin content, doorway patterns,
manual actions or indexing anomalies. Public publication still requires the
customer's explicit approval.

## P2 campaign-opening wizard

After P1 creates an isolated installation, P2 converts one plain-language
customer instruction into a complete, reviewable campaign:

```bash
python scripts/open_campaign.py --brief \
  'כאשר מחפשים X / X2, אני רוצה שהמשתמש יקבל Y, דרך הנכסים A / B / https://example.org/profile, תוך איסור על Z / Z2.'
```

The command creates `data/campaign_draft.json` with primary and secondary
queries, desired facts and narratives, Google and AI targets, resolved and
unverified assets, approval rules, content limits and installation-specific
success metrics. It does not publish anything.

The customer reviews the exact draft and supplies its content-bound approval
ID:

```bash
python scripts/open_campaign.py --approve campaign-0123456789abcdef
```

Any edit changes the approval ID and invalidates the old approval. Activation
updates the isolated installation transactionally, queues ownership and
baseline checks, and preserves item-level approval for every public
publication. A structured intake is also supported:

```bash
python scripts/open_campaign.py \
  --intake-json config/campaign_intake.example.json
```

Customer-proposed facts remain pending until evidence and owner approval exist;
desired narratives never override the approved fact registry.

## P3 real Google and AI measurement

Every monitor cycle now stores a versioned `visibility_measurement` in
`data/command_center.json`. Search measurements record controlled, desired and
negative top-ten results; reciprocal-rank weights; SERP feature presence; and
7/28-day volatility. The key includes engine, surface, interface, collection
method, query, locale and device, so unlike observations are never averaged.

AI measurements separately report identity accuracy, fact-registry accuracy,
desired-narrative coverage, approved-source citation rate/share, source
diversity, harmful-or-incorrect frequency and cross-sample stability. Engine,
surface, API versus consumer interface, collection method, model, locale and
prompt are immutable grouping dimensions. An API response is never presented
as a consumer-interface result.

The scheduled pilot measures Google and Bing web results through SerpApi. This
uses additional provider queries and can be changed with `SERP_ENGINES`.

Bing Webmaster Tools AI Performance is kept as a separate consumer-UI data
source. Because no documented public export API is assumed, import only an
export the customer is authorized to access:

```bash
python scripts/import_bing_ai_performance.py \
  --input /path/to/authorized-bing-ai-performance.csv
```

CSV and JSON are accepted; an example is
`config/bing_ai_performance.example.csv`. The normalized data is saved under
the active single-tenant installation as `data/bing_ai_performance.json` and
the next monitor run reports citations, cited pages and grounding queries.
No undocumented endpoint or browser scraping is used.

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
| Reviewed Content | Mon/Wed/Fri | Generate a durable medical draft; publish only an explicitly approved draft |
| Social Distribution | Mon/Wed/Fri | Distribute approved content when not frozen |
| Schema Sync | Weekly | Keep connected site facts and structured data aligned |

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the data model, routing
rules, governance boundaries and planned premium layers.
The Hebrew operator guide and research summary is
[docs/REPUTATION_STRATEGY_HE.md](docs/REPUTATION_STRATEGY_HE.md).
The premium Google/AI control loop and critical new-asset policy are documented
in [docs/PREMIUM_SERP_AI_ENGINE_HE.md](docs/PREMIUM_SERP_AI_ENGINE_HE.md).

### Reviewed Medium publishing

Scheduled runs create a Markdown file under `content_drafts/` and do not publish
it. The private reputation dashboard displays each pending draft and provides
one **Approve and publish** action. The approval queue is collected
automatically by GitHub Actions, and the resulting Medium URL is recorded under
`content_drafts/published/`. Legacy Medium API tokens are preferred when one
already exists; the session-cookie route is a fallback and records HTML and
screenshots when Medium rejects or changes the browser flow.
