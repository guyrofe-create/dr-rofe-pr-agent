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

The distribution layer transforms one approved source into platform-native
Facebook, LinkedIn, Pinterest, Blogger and Google Business variants. The
variants cannot introduce new facts.

## Media

Generated images retain a known visual description. Alt text describes that
visual and includes the entity name only when the entity is actually relevant.
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
