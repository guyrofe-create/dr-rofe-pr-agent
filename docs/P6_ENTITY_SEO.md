# P6 — Content and Entity SEO layer

P6 makes the approved identity and authorship machine-readable while preserving
the product's item-level approval boundary. It does not promise rankings,
indexing, citations, AI inclusion or a knowledge panel.

## Entity graph

`data/business_profile.json` is the source of truth. The core emits:

- one stable canonical `Person` identifier (`canonical-site/#person`);
- a visible `ProfilePage` whose `mainEntity` is that Person;
- `Article` markup whose `author` links to the same Person and visible profile;
- consistent approved name variants, biography, image, official links and
  `sameAs` values.

The scheduled schema workflow is audit-only. A public ProfilePage sync runs
only through a manual workflow dispatch with `publish_approved=true`. This
prevents a schema job from silently creating or overwriting a public page.

## Content quality

Drafts must answer the central question before expanding, use clear headings
and cite at least two direct sources. Primary and official sources are
preferred. Tables and FAQs are conditional: they are used only when they make
a real comparison or answer real questions. Original analysis must be
distinguished from sourced fact.

For medical content, at least two exact external sources must also be linked
inside the article body next to the claims they support, using descriptive
anchor text. The same URLs remain in the Sources section for auditability.
Direct professional guidance, systematic reviews, primary research and public
health authorities take precedence. News sites may document a dated news event
or an interview, but they are not accepted as evidence for a medical claim.
Homepage links, search-result links and generic anchors such as "click here"
fail the content gate.

The distribution layer transforms one approved source into platform-native
Facebook, LinkedIn, Pinterest and Blogger variants. The variants cannot
introduce new facts. Google Business Profile publishing is disabled unless
independent eligibility and API access are verified.

Every approved article must visibly bind the content to the configured client:
the canonical name appears once in the title, the linked byline points to the
profile, a truthful author box states the current role and non-practising
status, and the body uses the name naturally rather than through keyword
stuffing. The same entity contract drives the meta description and
platform-native signatures.

## Media

Each approval package contains four exact image variants: a text-free article
hero, a landscape social card, a square card and a portrait Pinterest card.
GPT Image creates a topic-relevant, text-free editorial base when available.
The product then renders the exact approved Hebrew title and client name itself,
so generated lettering cannot corrupt the brand. If the image API is
unavailable, a deterministic branded renderer produces the complete package;
the workflow never downgrades to an image-free article.

Alt text describes the actual branded information card, includes the canonical
client name exactly once and naturally names the article subject. It is written
for accessibility first and is not a keyword list. Licensed photographs may
still be selected manually; their creator, source, licence, attribution and
known visual description are preserved.
Video packages fail validation without captions and a transcript.

## Search crawler audit

`python3 scripts/crawler_audit.py` performs a read-only check of each configured
site's `robots.txt` for Googlebot, Bingbot, OAI-SearchBot and PerplexityBot. It
produces `crawler_audit.json`. A weekly workflow uploads that report as an
artifact and makes no site change.

Allowing a crawler is a prerequisite for crawling, not a guarantee of
appearance or citation. Search crawling and model-training controls are not
treated as interchangeable.

Official references:

- Schema.org [`ProfilePage`](https://schema.org/ProfilePage)
- Schema.org [`Article`](https://schema.org/Article)
- OpenAI [Publishers and Developers FAQ](https://help.openai.com/en/articles/12627856-publishers-and-developers-faq)
- Perplexity [crawler documentation](https://docs.perplexity.ai/docs/resources/perplexity-crawlers)

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q scripts tests
```
