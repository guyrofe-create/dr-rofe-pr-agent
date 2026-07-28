# P7 — approval and publication

P7 is the only public-execution gate. Drafting, research, licensed-photo
selection and previewing may be autonomous; publication may not be inferred from a boolean,
a schedule, an earlier campaign approval or a general account permission.

If automatic licensed-photo selection cannot find a truthful topic-relevant
image, the draft and review bundle are still preserved with
`image_status: awaiting_replacement`. The dashboard may request another
licensed-photo search, but approval and publication remain blocked until the
exact bundle contains approved media.

## One exact approval package

Every public action is represented by one immutable JSON bundle and one
human-readable HTML preview. The package contains:

- the exact payload for every platform and asset;
- the approved photo bytes or URI, their SHA-256 when local, visual description,
  exact alt text, creator, source page, licence and required attribution;
- sources;
- the objective and search query served;
- risk and compliance notes;
- every sensitive scope that needs an explicit decision.

`approval_id` is a SHA-256 digest of all material fields. Text, target, media,
alt text, source, risk, compliance, objective or scope edits therefore produce
a different ID and invalidate the approval.

The server signs the decision with HMAC-SHA256. The signing secret must exist
only in the installation's secret store. A client-supplied `approved=true`
value is never sufficient.

## Always-explicit actions

Public publication always requires `public_publication`. These additional
scopes are never implied and must be separately present when relevant:

- `domain_purchase`
- `account_creation`
- `medical_content`
- `legal_claim`
- `external_outreach`

The action is blocked when even one required scope is absent.

## Safe execution and receipts

Each destination gets an idempotency key derived from the approval ID and
target ID. Before calling a remote platform, P7 records `in_progress`.

- A completed target returns its stored public URL and provider receipt without
  calling the platform again.
- A lost or ambiguous response becomes `reconciliation_required`; P7 does not
  retry because the remote platform may already have accepted the post.
- A successful target stores the exact request hash, platform, asset, public
  URL, timestamps, idempotency key and provider receipt.

The aggregate campaign receipt is stored under `content_drafts/campaigns/`;
the per-target execution ledger is stored under `publication_receipts/`.

## Operator flow

Prepare the exact content and media before approval:

```bash
python3 scripts/prepare_approval_bundle.py content_drafts/example.md \
  --image-uri approval_bundles/media/example.png \
  --image-sha256 <sha256> \
  --image-alt-text "Truthful description of the approved image"
```

Review the generated `.html`. The approval service then records every explicit
scope. The CLI below is intended for a trusted operator environment and expects
the signing secret in the server-side environment:

```bash
APPROVAL_SIGNING_SECRET=... python3 scripts/approve_bundle.py \
  approval_bundles/apr_....json \
  --approved-by customer-id \
  --scope public_publication \
  --scope medical_content
```

The dashboard queue must return `draft_path`, `bundle_path` and
`approval_record_path`. `campaign_run.py` verifies all three and the signature
before any external call. `PUBLISH_APPROVED=true` no longer authorizes
publication.

## Fail-closed boundaries

- No image or public text is generated after approval.
- A bundle marked as requiring an approved image cannot be signed or executed
  while its media field is empty.
- Implicit fan-out to an asset not listed in the bundle is blocked.
- Instagram and TikTok remain owner-managed for the pilot; X remains disabled.
- A different canonical URL stops distribution and requires reconciliation.
- Legacy generate-and-publish social automation is disabled.
- Preparation and tests never perform a public action.
