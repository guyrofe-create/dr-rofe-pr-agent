# Reputation Command Center architecture

## Operating loop

`Listen -> Understand -> Score -> Route -> Approve -> Act -> Measure -> Learn`

`config/reputation_strategy.json` is the machine-readable operating doctrine.
It is loaded and validated at runtime. Content generation, publication-channel
guards, growth planning, AI prompt selection, repeated sampling and metrics all
consume it; the strategy is not merely documentation.

`data/fact_registry.json` is the evidence gate for public identity facts.
Approved facts require evidence records; unknowns remain explicit and cannot be
silently filled by the content model.

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
- Preserve the guyrofe.com homepage; entity work belongs on dedicated pages.
- Instagram is product-managed only through an exact approved licensed-photo
  payload and the official professional-account API. TikTok remains
  owner-managed, X remains disabled, and Telegram or Tumblr require a distinct
  audience purpose before product activation.
- Medical drafts require human review and at least two direct authoritative sources.

## Aggressive growth engine

The growth layer pursues high cadence and maximum controllable coverage without
using tactics that can invalidate the client's durable assets. Every monitor run
updates observable gaps and replans a campaign across these surfaces:

- branded Google/Bing result coverage with a diversified asset portfolio;
- local relevance and prominence;
- canonical entity facts and third-party corroboration;
- passage-level expert answers for retrieval and citation;
- original research and digital PR;
- content refresh opportunities rather than scaled thin pages;
- valid policy/legal correction and removal paths.

Each tactic declares impact, speed, risk, prerequisites, actions and forbidden
shortcuts. Campaign measurement deliberately separates traditional ranking,
local share of voice, AI citation share, explicit brand mentions, sentiment and
qualified business outcomes. Ranking and citation are outcomes, never promises.

### Query-level SERP and AI orchestrator

`config/serp_targets.json` defines every approved brand query, target market,
property role and measurable objective. Every daily monitor cycle preserves the
complete top ten, builds a control map and calculates weighted desired share,
controlled positions and negative positions. The Search Console adapter uses
the shared Google OAuth refresh token to add 28-day query/page evidence.

AI samples are measured separately for factual accuracy, approved-source
citation rate and approved citation share. Asset activation, page refresh,
defense, displacement and AI correction work is proposed from evidence rather
than from a fixed publishing calendar.

`config/asset_blueprints.json` and `editorial_radar.py` contain creative
property and medical-news patterns. They do not authorize construction. The
new-asset gate may require incubation inside an existing property or reject an
attractive idea when it would split authority, duplicate intent or create an
unsustainable YMYL surface.

The `health_news_radar.yml` workflow activates only the research-intake part
of the medical-news pattern for `DRGUYROFE_CO_IL`. It retrieves allowlisted RSS
metadata, creates one evidence-research brief, and sets
`public_execution_allowed: false`. Article generation, media selection,
medical approval and WordPress publication remain separate phases. The
autonomous cadence may perform the generation and media-preparation phases,
while signed medical and publication approval remains mandatory.

`autonomous_content.yml` consumes the explicit weekly plan in
`config/content_cadence.json`. It may prepare two site-specific content streams
and platform-native variants, but it cannot approve or publish them. The
selected WordPress site key and exact scheduled channels are embedded in the
immutable approval bundle, preventing implicit fan-out and cross-domain
duplication.

### Asset governance

`data/asset_registry.json` is the single credential-free inventory of owned and
earned properties. Assets are classified as A (core), B (selective), C (retain
only with a real purpose) or Q (quarantined). The monitor may plan campaigns from
A/B assets, but it never treats mere asset existence as page-one visibility.
Only independently observed page-one positions count toward SERP coverage.

`owner_inventory` preserves the exact profile links confirmed by the owner,
including unresolved entries such as a Telegram channel without a URL. Canonical
asset records remain normalized for monitoring and automation. Private connection
spreadsheets may be named in `inventory_sources`, but their URLs, usernames,
passwords and tokens are never copied into the repository.

Generic Web 2.0 mirrors, irrelevant profiles and duplicate-content properties
remain disabled until a separate factual, content and indexation audit proves a
real user purpose. Credentials must live only in an encrypted secret store and
must never be copied into the repository or asset registry.

## Deployment model

The product is single-tenant by design: each purchased installation operates
for one client only. `config/client_profile.json` contains that installation's
queries, desired search outcome, canonical facts, channel ownership, approval
rules, AI evaluation rules and sustainable asset-volume policy. Product logic
must not contain a client name, domain or search query.

The asset gate has no universal "safe number" of sites or posts. Capacity is
computed separately for each installation from independent value, portfolio
diversity, authority, maintenance capacity and observed index health. Doorway
patterns, cloned intent, cannibalization, thin content, manual actions and
indexing anomalies automatically stop expansion. New ideas that are not yet
proven are incubated as a section or series inside a stronger existing
property.

`scripts/install_client.py` is the setup wizard. It accepts a customer-owned
installation specification and creates exactly one client profile, its facts,
assets, search targets, campaign and secret-name manifest. The generic engine
contains no customer name, domain, query or content agenda; these live only in
the isolated installation. `REPUTATION_INSTALLATION_ROOT` selects that
installation at runtime.

## P2 campaign-opening wizard

P2 is a gated translation layer between customer intent and the runtime
configuration. It accepts either the documented Hebrew sentence contract or a
structured JSON intake. `scripts/open_campaign.py` then builds an immutable
review bundle containing:

- primary and secondary queries;
- approved facts, pending fact proposals and desired narratives;
- separate Google and AI visibility targets;
- verified existing assets and assets awaiting ownership verification;
- customer and installation approval rules;
- merged content constraints; and
- measurable, installation-specific success criteria.

The bundle receives a deterministic approval ID derived from every material
field. A changed bundle cannot be activated using an earlier approval. Exact
approval projects the campaign into the single-tenant profile, target,
strategy, fact and asset files as one rollback-capable transaction. It does not
publish content. New facts remain excluded until evidence-approved, unverified
assets remain uncontrolled, and each public item still requires explicit
approval.

## P3 independent visibility measurement

P3 adds a measurement layer, not a ranking promise. A SERP observation is keyed
by engine, surface, interface, collection method, query, country, language and
device. It records controlled and desired results independently, position
weights, negative exposure, knowledge panel/image/video and other SERP feature
presence, and 7/28-day volatility. Missing results are treated as position 11
for movement calculations.

An AI observation is keyed separately by engine, surface, interface,
collection method, model, country, language and exact prompt. Metrics cover
identity correctness, fact-registry accuracy, desired narrative coverage,
approved-source citations, source diversity, harmful or wrong information and
agreement across repeated samples. Unknown factual accuracy fails closed; it
is not silently counted as correct.

`monitor_run.py` persists both layers inside the command center. OpenAI API
sampling remains explicitly labeled as an API surface. Consumer UI samples
must be collected through an authorized workflow and cannot be blended with
the API. Bing AI Performance CSV/JSON exports are normalized by
`import_bing_ai_performance.py`; the adapter deliberately does not invent or
scrape an undocumented Bing export API.

## P4 opportunity-ranked execution

P4 turns P3 evidence and the existing action planner into one scored portfolio.
Each candidate is normalized to one of nine action types and scored on seven
1-10 factors:

`impact × authority × relevance × control ÷ (time + financial cost + risk)`

The score is a prioritization aid, not a ranking guarantee. Evidence and
confidence remain visible. Selection applies an installation-specific minimum
score, total capacity, per-asset concentration, risk ceiling, and high-risk
capacity. Quarantined assets, owner-managed channels, disabled channels and
new-asset proposals rejected by the safety gate cannot be selected.

P3 gaps can produce content, media, connection, external-mention,
fact-correction and lawful correction/removal opportunities. Existing asset
and content evidence supplies strengthening and refresh actions; the P1 asset
gate supplies new-asset proposals. The engine deduplicates stable opportunity
IDs before ranking.

Every selected opportunity is prepared by `prepare_opportunities.py` as an
immutable JSON bundle plus a human-readable review sheet. Existing bundles are
never regenerated, so the two-hour monitor is idempotent. Preparation is
allowed during a content freeze, but public execution remains disabled. Every
action type—including outreach and correction requests—requires exact
item-level approval and a new approval after any edit.

## P5 controlled creative asset engine

`creative_asset_engine.py` consumes the P3 query-control map, the credential-free
asset registry, content fingerprints, creation history and the installation's
asset policy. A measured gap is an investigation trigger, never permission to
create another result. The engine ranks exactly six extensible archetypes:
authoritative profile, YouTube/video series, knowledge library, genuine-project
portfolio page, standalone systemic asset, and independent earned contribution.

Every candidate carries a five-part evidence dossier:

- separate systemic purpose;
- real reader value;
- sustainable maintenance;
- reasonable ranking/discovery path; and
- no duplication or doorway pattern.

Missing evidence yields `evidence_required`; a viable concept that should be
tested inside an existing property yields `incubate`; a hard-stop signal yields
`reject`. `build` is possible only after all five proofs pass and, for controlled
properties, the existing maintenance and portfolio-capacity gate also passes.
Standalone properties need proof of value without reputation benefit and proof
that an existing property cannot serve the same purpose. Independent coverage
needs verified editorial independence and is not misrepresented as a controlled
asset.

P5 candidates are converted to P4 opportunities with an explicit authorization
scope. Evidence collection, existing-asset incubation and build-brief
preparation are separate scopes. `new_asset_build_authorized` remains false:
account creation, site/channel creation, outreach and publication require a
separate exact owner approval. The dashboard and monitor report expose the
candidate, its five proof states, missing evidence and gate outcome.

## Next premium layers

1. Approval UI and executor adapters for each P4 action type.
2. Encrypted connector vault and role-based approvals for a single installation.
3. Unified inbox for review, social, news, forum, email and CRM events.
4. Contextual response drafting with privacy and policy validation.
5. Review-request journeys without review gating or incentives.
6. Narrative map and entity knowledge graph for search and AI consistency.
7. Root-cause analysis that turns recurring complaints into operational tasks.
8. Authorized consumer-interface AI sampling beyond the implemented API and
   Bing AI Performance import surfaces.
9. Outcome analytics: response time, resolution, sentiment recovery, leads and revenue.
# P7 public-execution boundary

Public execution is separated from preparation by an immutable approval
artifact. `approval_workflow.py` hashes all material fields, requires explicit
action scopes, verifies the server HMAC and maintains a durable target-level
execution ledger. `prepare_approval_bundle.py` creates the review package and
HTML preview; `campaign_run.py` accepts only a matching signed approval record.

The ledger writes `in_progress` before the remote call. Completed entries are
returned as receipts on repeated runs. Ambiguous entries require reconciliation
and are never retried automatically. This provides fail-closed at-most-once
behavior where a provider lacks a native idempotency API.
