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
- binds every article and platform variant to the client through a branded title,
  visible linked byline, truthful author box, natural entity mentions and
  entity-aware metadata;
- creates an approved four-format visual package with GPT Image when available
  and a deterministic branded fallback, so an image failure cannot silently
  produce an image-free approval package;
- maps first-page asset gaps and separates AI citations from explicit brand mentions;
- maintains a credential-free A/B/C/Q asset registry and excludes quarantined Web 2.0 mirrors from automation;
- treats `drguyrofe.com` as a connected Wix evergreen medical-knowledge hub;
- registers `guyrofe.wixsite.com/homepage` separately as a gated media-transcript
  archive, never as a content mirror;
- binds every draft stream to one owned property and blocks exact or near
  cross-domain duplicates before approval;
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

The default single-tenant installation uses a conservative SerpApi free-tier
policy from `config/serp_targets.json`: the two highest-value core queries are
measured daily on Google mobile, while the full query, engine and device matrix
plus web-mention discovery runs weekly. Successful provider requests are
accounted per calendar month, repeated partial runs reuse a persisted daily
cache, and collection stops at 220 requests to retain 30 of the free plan's 250
searches for manual checks or accounting drift.

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
inventory. Wix publishing for `drguyrofe.com` requires
`WIX_PRIMARY_DRGUYROFE_COM_API` and
`WIX_PRIMARY_DRGUYROFE_COM_SITE_ID`. The older
`WIX_DRGUYROFE_COM_*` names belong only to the supporting
`guyrofe.wixsite.com/homepage` site.

Content freeze cannot be removed while an active crisis room exists.

## P4 opportunity and action engine

The monitor no longer relies on fixed weekdays to decide what deserves work.
Every two-hour evidence cycle generates and ranks opportunities using:

`expected impact × asset authority × query relevance × control ÷ (time + cost + risk)`

All seven inputs use a documented 1-10 scale. The portfolio enforces a minimum
score, per-cycle capacity, per-asset concentration, a risk ceiling and a
high-risk capacity. It supports strengthening an asset, correcting a fact or
profile, creating or refreshing content, connecting assets, creating media or
a page, proposing a new asset, preparing a correction/removal request, and
earning an external mention.

The highest-ranked eligible items are converted into durable JSON and Markdown
work orders under `opportunity_drafts/`. Preparation is autonomous and
idempotent. Every bundle has `public_execution_allowed: false`; the exact item
must be approved before any public change, publication, outreach, correction
or removal request. Owner-managed and quarantined assets remain blocked.

The old reviewed content generator is retained for manual use only. The
two-hour monitor is the automatic trigger for P4 planning and preparation.

## drguyrofe.co.il Israeli health-news desk

The independent `drguyrofe.co.il` phase-one radar runs once each morning and
reads metadata from configured official Israeli health-news RSS feeds. It
filters sponsored markers, rejects links outside each publisher's allowlist,
ranks recent medically relevant stories, and applies a soft source cooldown so
one publisher does not dominate when comparable alternatives exist.

The selected item becomes a review-only brief under `opportunity_drafts/`. The
brief links visibly to the original news report and requires primary-source
research plus at least two additional authoritative sources. The radar stores
only feed metadata and a short summary; it does not copy article bodies, call
OpenAI, generate images, write the final medical article, or publish anything.
If no candidate passes the quality threshold, it creates no brief.

Run it manually with:

```bash
python scripts/health_news_radar.py
```

## Autonomous editorial cadence

`config/content_cadence.json` is the single source of truth for preparation
frequency. On weekdays, the product autonomously creates only drafts and exact
licensed-photo approval packages:

- `guyrofe.com`: two evidence-led depth articles per week;
- `drguyrofe.co.il`: up to five evidence-led health-news analyses per week,
  never more than one per weekday and only when an eligible unused news brief
  exists;
- `drguyrofe.com`: one original evergreen medical guide per week, never an echo
  of another owned domain;
- `guyrofe.wixsite.com/homepage`: no quota. A unique transcript companion can
  enter review only when a real podcast/video URL and transcript exist, at
  least 14 days after the previous archive item, and after the legacy-content
  audit has passed. `רפואה על כוס קפה` is registered as the official podcast
  source; podcast briefs require verified transcript text plus episode links
  for both Spotify and Apple Podcasts;
- Facebook and LinkedIn: four distinct native variants per week;
- Pinterest: three image-required variants per week;
- Instagram: two image-required variants per week through the professional
  account API when its permission check passes;
- Blogger: two short, distinct summaries per week rather than article copies.

The monitor runs twice daily. The news radar runs before the weekday content
cadence. A missing quality story, approved source, licensed photograph or
platform connection causes that destination to be skipped or held—not replaced
with weak content. Every public action remains blocked behind the signed P7
medical and publication approval.

Wix publication uses the official Blog Draft Posts API, preserves links by
converting the exact approved HTML to Wix Ricos rich content, checks the
approved slug for idempotency, and publishes only the single Wix target present
in the signed bundle. A monthly read-only Wix audit reports legacy,
placeholder, service and booking URLs; it never modifies the sites.

## P5 controlled creative asset engine

P5 investigates a new asset only when P3 measures a desired-result gap. It can
propose six controlled archetypes: an authoritative platform profile, a
YouTube channel or video series, a knowledge library, a books/apps/research/
projects page, an exceptional standalone systemic property, or an independent
guest article/interview/data-led study. Existing asset types are suppressed so
the engine does not propose a duplicate profile or channel.

No proposal is build-ready until it proves all five conditions:

1. a separate systemic purpose, audience and intent;
2. independently useful reader value and an original launch inventory;
3. an accountable owner, cadence and at least 12 months of capacity;
4. a realistic authority, discovery and measurement path; and
5. completed duplication, similarity and doorway-pattern review.

A standalone site must additionally prove that it remains valuable without any
reputation benefit and cannot coherently fit an existing asset. Earned media
must prove genuine editorial independence. Hard-stop signals reject a
candidate; incomplete evidence produces an evidence-only work order; viable
ideas may first be incubated inside an existing asset. Even a `build` outcome
only authorizes preparation of a brief. Creating an account, site, channel,
outreach or publication always requires separate item-level owner approval.

## P6 content and Entity SEO layer

P6 maintains a stable `Person` identity graph, a visible `ProfilePage`, and
`Article` markup that links each canonical article to the approved author
profile. Names, biography, image and official `sameAs` links come from the
single-tenant business profile.

The content gate requires an answer-first opening, clear headings and direct
sources. Tables and FAQs are conditional rather than decorative. Distribution
uses fact-bounded, platform-native variants instead of copying one caption
unchanged. Every article is visibly bound to the client in its title, linked
byline, author box and natural body mentions.

Review media is generated as one immutable four-format package: hero,
landscape, square and portrait. Every variant is text-free. The product searches
Wikimedia Commons and Openverse for a topic-relevant photograph with a verified
compatible license, preserves its attribution and uses AI only for relevance
review. AI image generation is disabled; if no photograph passes, the bundle
stops for manual image selection.
The approval step fails closed unless every required image and its entity-aware
alt text are present. Wikimedia remains an optional licensed-photo utility, not
the critical path. Video metadata requires captions and a transcript.

The weekly schema workflow is audit-only unless an operator manually supplies
`publish_approved=true`. It also runs a read-only robots audit for Googlebot,
Bingbot, OAI-SearchBot and PerplexityBot. Crawler access is recorded as a
technical prerequisite and never presented as a promise of indexing, ranking
or AI citation. See [docs/P6_ENTITY_SEO.md](docs/P6_ENTITY_SEO.md).

## P7 signed approval and idempotent publication

Every public action now starts from one immutable approval bundle containing
the exact per-platform text, target asset, image and alt text, sources,
objective/query, risk, compliance notes and preview. A material edit changes
the bundle hash and invalidates its signed approval. A boolean input is not an
approval.

Publication, domain purchases, account creation, medical content, legal claims
and external outreach have explicit scopes; every applicable scope must be
approved. Execution uses a durable per-target idempotency ledger. A completed
target returns its existing URL and receipt without posting twice. An ambiguous
remote response stops for reconciliation instead of retrying. No text or image
is generated after approval and no asset receives implicit fan-out.

See [docs/P7_APPROVAL_AND_PUBLISHING.md](docs/P7_APPROVAL_AND_PUBLISHING.md).

## Automated workflows

| Workflow | Schedule | Purpose |
|---|---|---|
| Reputation Monitor + P4 | 1st and 15th of each month | Measure Google, AI answers and Search Console; prepare eligible actions |
| Autonomous Content Cadence | Sunday-Thursday | Prepare cadence-due drafts and licensed-photo bundles; never publish without approval |
| Legacy Reviewed Content | Manual only | Generate a manually requested durable medical draft |
| Signed P7 Distribution | Manual or approval queue | Verify the exact signed bundle, publish idempotently and record URLs/receipts |
| Weekly Email Report | Sunday | Email AI tokens/cost, completed actions, verified publication receipts and live links |
| Schema + crawler audit | Weekly | Preview entity consistency and crawler access; public sync requires explicit approval |

The weekly report is sent to `guyrofe@gmail.com` through Gmail SMTP. Add a
Google App Password as the repository secret
`WEEKLY_REPORT_GMAIL_APP_PASSWORD`; the account password itself must never be
stored. The report records only usage totals and costs—never prompts or model
outputs—and lists a publication only when the execution ledger contains a URL.

Every new image-ready P7 bundle also triggers one immediate email to
`guyrofe@gmail.com`. The message contains the exact approval ID and a link to
the approval dashboard. Delivery IDs are recorded so the same bundle is not
emailed twice. The notification workflow is triggered after every workflow
that creates or replaces an approval bundle, with a daily recovery run.

Create a podcast transcript brief with:

```bash
python scripts/podcast_episode_intake.py \
  --title "שם הפרק" \
  --transcript verified-transcript.md \
  --spotify-url "https://open.spotify.com/episode/..." \
  --apple-url "https://podcasts.apple.com/...?...i=..."
```

This prepares an event-driven archive item; it does not authorize publication.

The connected YouTube OAuth integration is currently read-only. It verifies the
configured channel and allows an original YouTube URL plus transcript to enter
the same media-archive review flow. It does not upload videos, edit titles or
descriptions, replace thumbnails, or publish Community posts.

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
