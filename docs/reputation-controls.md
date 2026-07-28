# Reputation controls added in version 4

These controls are evidence-first and fail closed. They prepare monitoring,
proposals and approval packages; they do not perform external submissions.

## AI and search measurement

`config/serp_targets.json` keeps OpenAI, Google AI Overviews, Gemini,
Perplexity, Claude and Bing as separate dimensions. Consumer-interface samples
are imported with:

```bash
python3 scripts/import_ai_surface_samples.py sample.json
```

Browser samples require the full answer, prompt, model, timestamp, citations
and a SHA-256 hash of the preserved screenshot. The monitor loads the validated
samples from `data/manual_ai_samples.json`.

Google states that AI Overviews and AI Mode use the normal Search eligibility
and Googlebot controls; there is no separate special markup requirement:
https://developers.google.com/search/docs/appearance/ai-features

## Wikipedia, Wikidata and Knowledge Panel

The P5 portfolio now includes an independent-governance Wikimedia workstream.
It requires independent notability sources, conflict-of-interest disclosure and
a talk-page/requested-edit route. It never treats Wikipedia or Wikidata as a
controlled marketing property.

Knowledge Panel claiming is tracked as a manual ownership and evidence task.
No claim or edit is submitted automatically.

## Backlinks and disavow

`python3 scripts/reputation_controls.py audit-backlinks ...` compares snapshots
and flags documented risk patterns. A disavow proposal can contain only domains
already flagged for manual review. Submission is always blocked until explicit
approval; low-quality links alone are not treated as proof of negative SEO.

## Honest review requests

The review campaign builder accepts only recipients with a verified real
interaction and contact permission. It rejects any recipient data containing
rating, NPS, sentiment or likely-positive fields, disables incentives and never
sends automatically. FTC guidance prohibits review gating and incentives
conditioned on positive sentiment:
https://www.ftc.gov/business-guidance/resources/consumer-reviews-testimonials-rule-questions-answers

## Legal evidence chain

Legal removal preparation requires a case number, court, official HTTPS
verification source, document URL, retrieval and verification timestamps,
verifier identity, court-record verification and a matching document SHA-256.
Even a passing chain remains blocked until explicit legal approval.

## Crawlers and credentials

The crawler audit distinguishes Search, training and user-requested fetch roles
for Google, OpenAI, Perplexity and Anthropic user agents. Allowing a crawler
does not guarantee inclusion.

Person schema supports `hasCredential`, but emits a credential only when its
record contains HTTPS evidence. The evidence metadata is removed from the
public JSON-LD. Schema.org defines `hasCredential` for `Person` and
`Organization`: https://schema.org/hasCredential

## AI feedback

The product can prepare a zero-cost, evidence-complete feedback task for an
incorrect AI answer. Submission remains a manual user action inside the
relevant consumer application; there is no invented API or automatic reporting.
