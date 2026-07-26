"""Evidence-aligned reputation growth tactics.

Aggressive means high cadence and fast execution, not policy abuse. Each tactic
records its expected surface, prerequisites, risk and forbidden shortcuts so the
agent can push hard without gambling the client's durable assets.
"""

TACTICS = {
    "new_asset_incubation": {
        "surface": ["google_brand_serp", "google_ai", "chatgpt", "perplexity", "bing_copilot"],
        "goal": "Create or earn a new useful retrieval surface when existing assets cannot close the measured gap",
        "impact": 10, "speed": 4, "risk": 2,
        "requires": ["measured_serp_gap", "distinct_audience_purpose", "maintenance_owner"],
        "actions": [
            "Choose the missing surface: publication, research library, video, podcast, documents, newsletter, Q&A or earned editorial coverage",
            "Define a distinct audience, query intent, editorial role and success metric",
            "Create original source-worthy material and connect it naturally to relevant approved assets",
            "Incubate for at least one review cycle, then expand, reposition or retire from measured outcomes",
        ],
        "forbidden": ["doorway_site", "cloned_domain", "fake_independence", "mass_low_value_content"],
    },
    "verified_fact_registry": {
        "surface": ["google", "google_ai", "chatgpt", "perplexity", "bing_copilot", "all_profiles"],
        "goal": "Keep every identity claim traceable to an approved fact and evidence source",
        "impact": 10, "speed": 9, "risk": 1,
        "requires": ["owner_fact_approval", "evidence_links"],
        "actions": [
            "Record names, roles, credentials, dates, works, official URLs and current practice status",
            "Attach a primary or reliable independent evidence source to each material fact",
            "Mark disputed and unknown claims instead of filling gaps",
            "Use the registry as the only source for schema, biographies and platform profiles",
        ],
        "forbidden": ["unsupported_fact", "silent_fact_override", "fabricated_credential"],
    },
    "profile_consistency": {
        "surface": ["google", "google_ai", "chatgpt", "perplexity", "bing_copilot", "brand_serp"],
        "goal": "Align identity and current-status facts across official profiles",
        "impact": 9, "speed": 8, "risk": 1,
        "requires": ["verified_fact_registry", "profile_access"],
        "actions": [
            "Compare name variants, role, biography, image, website and current status",
            "Correct factual conflicts while preserving platform-native descriptions",
            "Link to the canonical source where the platform permits it",
            "Re-audit after material fact changes",
        ],
        "forbidden": ["cloned_spam_biography", "false_current_practice_claim"],
    },
    "entity_home": {
        "surface": ["google", "google_ai", "chatgpt", "perplexity", "bing_copilot"],
        "goal": "Create one canonical, richly evidenced entity home",
        "impact": 10, "speed": 7, "risk": 1,
        "requires": ["verified_facts", "canonical_site_access"],
        "actions": [
            "Create a dedicated person/organization page with stable URL and authorship",
            "Connect Person/Organization/LocalBusiness schema with stable @id values",
            "Link every official profile back to the canonical entity home where allowed",
            "Validate consistent name, role, location, credentials and sameAs references",
        ],
        "forbidden": ["fabricated_credentials", "fake_profiles"],
    },
    "brand_serp_asset": {
        "surface": ["google_brand_serp", "bing_brand_serp"],
        "goal": "Earn another useful, independent first-page brand result",
        "impact": 9, "speed": 6, "risk": 2,
        "requires": ["owned_or_earned_asset"],
        "actions": [
            "Select an asset type not already represented on page one",
            "Publish substantial platform-native content under the verified identity",
            "Link it naturally from relevant owned properties",
            "Maintain and update the asset until it earns branded-query relevance",
        ],
        "forbidden": ["doorway_sites", "cloned_content", "fake_independence"],
    },
    "original_research": {
        "surface": ["organic", "google_ai", "chatgpt", "perplexity", "digital_pr"],
        "goal": "Produce unique evidence that other sources can cite",
        "impact": 10, "speed": 4, "risk": 1,
        "requires": ["original_data", "expert_review"],
        "actions": [
            "Define a useful question and transparent methodology",
            "Publish data, limitations, concise findings and downloadable evidence",
            "Create citable passages, charts and journalist-ready summaries",
            "Pitch relevant journalists, associations and expert publishers",
        ],
        "forbidden": ["invented_statistics", "hidden_sponsorship"],
    },
    "expert_answer_library": {
        "surface": ["organic", "google_ai", "chatgpt", "perplexity"],
        "goal": "Own passage-level answers for high-value questions",
        "impact": 8, "speed": 7, "risk": 1,
        "requires": ["expert_review", "source_policy"],
        "actions": [
            "Map real customer questions and query fan-outs",
            "Lead sections with a direct answer followed by evidence and nuance",
            "Use stable headings, definitions, tables and source citations",
            "Update material facts and notify supported engines after changes",
        ],
        "forbidden": ["scaled_thin_pages", "keyword_stuffing"],
    },
    "digital_pr": {
        "surface": ["organic", "brand_serp", "google_ai", "chatgpt", "perplexity"],
        "goal": "Earn independent authority, mentions and editorial links",
        "impact": 10, "speed": 5, "risk": 2,
        "requires": ["newsworthy_asset", "approved_spokesperson"],
        "actions": [
            "Match evidence or expert commentary to journalists' active beats",
            "Pitch a specific useful angle rather than generic biography",
            "Respond rapidly with attributable, verifiable commentary",
            "Track unlinked mentions and request factual corrections or attribution",
        ],
        "forbidden": ["paid_dofollow_links", "fake_news_sites", "mass_spam_outreach"],
    },
    "local_prominence": {
        "surface": ["local_pack", "maps", "local_ai"],
        "goal": "Strengthen relevance and prominence for local intent",
        "impact": 9, "speed": 6, "risk": 1,
        "requires": ["verified_business_profile", "real_location"],
        "actions": [
            "Complete accurate categories, services, hours, media and service areas",
            "Keep NAP and core facts consistent across authoritative directories",
            "Request honest reviews from all eligible customers without gating",
            "Answer reviews and recurring questions with privacy-safe context",
        ],
        "forbidden": ["fake_location", "keyword_business_name", "review_gating", "incentivized_reviews"],
    },
    "content_refresh": {
        "surface": ["organic", "google_ai", "bing_copilot"],
        "goal": "Move an already-visible URL into a stronger retrieval position",
        "impact": 8, "speed": 8, "risk": 1,
        "requires": ["search_console_opportunity"],
        "actions": [
            "Prioritize pages with impressions and positions 4-20",
            "Resolve intent gaps, weak evidence, outdated facts and internal-link deficits",
            "Preserve the stable URL and update only when value materially improves",
            "Measure query, page, conversion and AI-impression changes",
        ],
        "forbidden": ["date_churn", "cosmetic_rewrite", "query_cannibalization"],
    },
    "policy_removal": {
        "surface": ["reviews", "search_results", "platforms"],
        "goal": "Remove or correct content only through a valid policy or legal path",
        "impact": 10, "speed": 3, "risk": 3,
        "requires": ["preserved_evidence", "specific_policy_basis"],
        "actions": [
            "Preserve URL, content, timestamps, identity and supporting evidence",
            "Map the exact policy or legal basis",
            "Submit one precise request and track the decision",
            "Use the permitted appeal or correction path if rejected",
        ],
        "forbidden": ["false_claim", "mass_report", "promise_removal", "intimidation"],
    },
    "ai_answer_correction": {
        "surface": ["google_ai", "chatgpt", "perplexity", "bing_copilot"],
        "goal": "Correct persistent factual errors at the source and verify recovery",
        "impact": 10, "speed": 5, "risk": 2,
        "requires": ["preserved_answer", "verified_fact_registry"],
        "actions": [
            "Preserve prompt, exact answer, model, date, language, citations and screenshot",
            "Correct the source used by the engine before publishing a rebuttal",
            "Publish a short evidence-backed clarification only when a source gap exists",
            "Request re-indexing and report the error through the engine's official path",
            "Close only after three consecutive clean re-tests",
        ],
        "forbidden": ["mass_generated_rebuttals", "unsupported_correction", "source_attack"],
    },
}


def ranked_tactics(surface=None, max_risk=3):
    choices = []
    for key, tactic in TACTICS.items():
        if tactic["risk"] > max_risk:
            continue
        if surface and surface not in tactic["surface"]:
            continue
        choices.append({"id": key, **tactic})
    return sorted(choices, key=lambda item: (item["impact"] * 2 + item["speed"] - item["risk"] * 2), reverse=True)
