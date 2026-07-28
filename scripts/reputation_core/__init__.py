"""Core primitives for the Reputation Command Center."""

from .command_center import CommandCenter
from .growth import plan_growth_campaign
from .editorial_radar import build_news_analysis_brief, rank_news_candidates
from .orchestrator import evaluate_new_asset_hypothesis, orchestrate_reputation_cycle
from .search_console import fetch_search_console_rows, refresh_google_access_token
from .installation import (
    assert_isolated_installation,
    config_path,
    data_path,
    installation_root,
)
from .coverage_safety import evaluate_coverage_safety
from .creative_asset_engine import (
    ASSET_ARCHETYPES,
    MANDATORY_PROOFS,
    build_creative_asset_portfolio,
    candidate_to_action,
    evaluate_creative_asset_candidate,
)
from .campaign_wizard import (
    apply_approved_campaign,
    build_campaign_draft,
    campaign_approval_id,
    parse_plain_language_brief,
    validate_campaign_draft,
)
from .measurement import (
    add_serp_volatility,
    measure_ai_surfaces,
    measure_serp_surface,
    summarize_bing_ai_performance,
)
from .opportunity_engine import (
    build_opportunity,
    build_opportunity_portfolio,
    score_opportunity,
    select_opportunities,
)
from .entity_seo import (
    audit_article_markdown,
    build_article_schema,
    build_person_schema,
    build_profile_page_schema,
    validate_media_metadata,
)
from .entity_contract import (
    EntityContext,
    EntityContractReport,
    apply_article_contract,
    audit_article_entity_contract,
    build_entity_context,
    meta_description,
    title_with_entity,
)
from .reputation_controls import (
    audit_backlinks,
    build_ai_feedback_task,
    build_disavow_proposal,
    build_knowledge_panel_task,
    build_review_request_campaign,
    build_wikimedia_workstream,
    validate_legal_evidence_chain,
)
from .platform_content import build_platform_variants, variants_are_distinct
from .approval_workflow import (
    ExecutionLedger,
    ReconciliationRequired,
    approval_id,
    approve_bundle,
    build_bundle,
    render_preview,
    validate_bundle,
    verify_approval,
)
from .onboarding import (
    build_installation_files,
    validate_install_spec,
    validate_installation_files,
    write_installation,
)
from .strategy import (
    client_asset_policy,
    client_content_plan,
    client_search_queries,
    load_client_profile,
    load_fact_registry,
    load_strategy,
    monitoring_prompts,
    success_metrics,
)

__all__ = [
    "CommandCenter",
    "plan_growth_campaign",
    "rank_news_candidates",
    "build_news_analysis_brief",
    "orchestrate_reputation_cycle",
    "fetch_search_console_rows",
    "refresh_google_access_token",
    "evaluate_new_asset_hypothesis",
    "load_strategy",
    "load_client_profile",
    "load_fact_registry",
    "client_search_queries",
    "client_asset_policy",
    "client_content_plan",
    "monitoring_prompts",
    "success_metrics",
    "installation_root",
    "config_path",
    "data_path",
    "assert_isolated_installation",
    "evaluate_coverage_safety",
    "ASSET_ARCHETYPES",
    "MANDATORY_PROOFS",
    "build_creative_asset_portfolio",
    "candidate_to_action",
    "evaluate_creative_asset_candidate",
    "build_installation_files",
    "validate_install_spec",
    "validate_installation_files",
    "write_installation",
    "parse_plain_language_brief",
    "build_campaign_draft",
    "campaign_approval_id",
    "validate_campaign_draft",
    "apply_approved_campaign",
    "measure_serp_surface",
    "add_serp_volatility",
    "measure_ai_surfaces",
    "summarize_bing_ai_performance",
    "score_opportunity",
    "build_opportunity",
    "select_opportunities",
    "build_opportunity_portfolio",
    "audit_article_markdown",
    "build_article_schema",
    "build_person_schema",
    "build_profile_page_schema",
    "validate_media_metadata",
    "EntityContext",
    "EntityContractReport",
    "apply_article_contract",
    "audit_article_entity_contract",
    "build_entity_context",
    "meta_description",
    "title_with_entity",
    "build_platform_variants",
    "variants_are_distinct",
    "audit_backlinks",
    "build_ai_feedback_task",
    "build_disavow_proposal",
    "build_knowledge_panel_task",
    "build_review_request_campaign",
    "build_wikimedia_workstream",
    "validate_legal_evidence_chain",
    "ExecutionLedger",
    "ReconciliationRequired",
    "approval_id",
    "approve_bundle",
    "build_bundle",
    "render_preview",
    "validate_bundle",
    "verify_approval",
]
