import type { SettingsResponse } from "../../hooks/settingsTypes";

export const WIKI_FEATURES_KEYS = [
  "wiki.tree_enabled",
  "wiki.dual_view_enabled",
  "wiki.cross_reference_enabled",
  "wiki.coverage_report_enabled",
  "wiki.stale_detection_enabled",
  "wiki.suggested_questions_enabled",
  "wiki.knowledge_injection_enabled",
  "wiki.cross_repo_domain_enabled",
  "wiki.auto_update_on_index",
  "wiki.mcp_server_enabled",
  "wiki.feedback_enabled",
  "wiki.lint_scheduler_enabled",
  "wiki.auto_heal_enabled",
  "wiki.deep_research_enabled",
  "wiki.concept_merging_enabled",
  "wiki.business_domain_enabled",
  "wiki.confidence_scoring_enabled",
  "wiki.contradiction_detection_enabled",
  "wiki.supersession_tracking_enabled",
  "wiki.memory_tiers_enabled",
  "wiki.forgetting_enabled",
  "wiki.schema_validation_enabled",
] as const;

export const WIKI_PIPELINE_CONCURRENCY_KEYS = [
  "wiki.compose_concurrency",
  "wiki.heal_concurrency",
  "wiki.domain_agent_concurrency",
  "wiki.module_compose_concurrency",
  "wiki.flow_compose_concurrency",
  "wiki.heal_max_rounds_core",
  "wiki.heal_max_rounds_standard",
  "wiki.llm_global_rpm_limit",
  "wiki.domain_split_threshold",
  "wiki.domain_split_max_depth",
] as const;

export const WIKI_GENERATION_KEYS = [
  "wiki.code_budget_enabled",
  "wiki.core_code_budget",
  "wiki.standard_code_budget",
  "wiki.skeleton_code_budget",
  "wiki.importance_core_percentile",
  "wiki.importance_standard_percentile",
  "wiki.rag_enabled",
  "wiki.rag_top_k",
  "wiki.rag_min_score",
  "wiki.enrichment_enabled",
  "wiki.enrichment_round1_enabled",
  "wiki.enrichment_round2_enabled",
  "wiki.business_wiki_batch_threshold",
  "wiki.lint_scheduler_interval_hours",
  "wiki.concept_merge_similarity_threshold",
  "wiki.confidence_weight_w1",
  "wiki.confidence_weight_w2",
  "wiki.confidence_weight_w3",
  "wiki.confidence_weight_w4",
  "wiki.confidence_weight_w5",
  "wiki.contradiction_similarity_threshold",
  "wiki.schema_path",
  "wiki.forgetting_initial_stability",
] as const;

export const WIKI_DOMAIN_AGENT_KEYS = [
  "wiki.domain_agent_max_iterations_core",
  "wiki.domain_agent_max_iterations_standard",
  "wiki.domain_agent_max_iterations_skeleton",
  "wiki.domain_agent_timeout_sec",
  "wiki.domain_agent_explore_max_rounds",
  "wiki.domain_agent_explore_max_tool_calls",
  "wiki.domain_agent_early_exit_quality",
  "wiki.domain_agent_early_exit_min_chars",
] as const;

export const WIKI_COMPOSITION_KEYS = [
  "wiki.wiki_content_language",
  "wiki.flow_compose_enabled",
  "wiki.guided_tour_enabled",
  "wiki.business_wiki_skip_repo_pages",
] as const;

export const WIKI_REASSEMBLY_KEYS = [
  "wiki.domain_reassembly_enabled",
  "wiki.reassembly_merge_threshold",
  "wiki.embedding_merge_threshold",
  "wiki.reassembly_orphan_threshold",
  "wiki.reassembly_max_moves_pct",
  "wiki.reassembly_respect_user_modified",
  "wiki.consolidation_min_count",
  "wiki.consolidation_min_domains",
] as const;

export const WIKI_HEALING_QUALITY_KEYS = [
  "wiki.heal_max_rounds_core",
  "wiki.heal_max_rounds_standard",
  "wiki.heal_loop_max_total_attempts",
  "wiki.heal_l2_threshold",
  "wiki.heal_on_l3_failure",
  "wiki.heal_l3_threshold",
  "wiki.quality_evaluation_mode",
  "wiki.quality_min_score",
  "wiki.quality_auto_heal",
  "wiki.quality_judge_model",
  "wiki.quality_sample_size",
] as const;

export const WIKI_DELEGATION_KEYS = [
  "wiki.delegation_enabled",
  "wiki.delegation_max_children",
  "wiki.delegation_max_code_lines",
  "wiki.delegation_grouping_strategy",
  "wiki.enrichment_enabled",
  "wiki.enrichment_round1_enabled",
  "wiki.enrichment_round2_enabled",
] as const;

export const WIKI_BUSINESS_DOMAIN_KEYS = [
  "wiki.business_domain_enabled",
  "wiki.business_domain_sub_batch_size",
  "wiki.business_domain_classify_timeout",
  "wiki.business_domain_max_concurrency",
  "wiki.business_domain_cache_ttl",
] as const;

export const WIKI_INCREMENTAL_BUDGET_KEYS = [
  "wiki.incremental_enabled",
  "wiki.resume_from_saved",
  "wiki.default_llm_budget",
  "wiki.code_budget_enabled",
  "wiki.core_code_budget",
  "wiki.standard_code_budget",
  "wiki.skeleton_code_budget",
  "wiki.importance_core_percentile",
  "wiki.importance_standard_percentile",
  "wiki.skeleton_strategy",
  "wiki.skeleton_light_model",
] as const;

export const WIKI_GIT_KEYS = [
  "wiki.git_publish_enabled",
  "wiki.git_publish_mode",
  "wiki.git_publish_trigger",
  "wiki.git_remote_url",
  "wiki.git_branch",
  "wiki.git_author_name",
  "wiki.git_author_email",
  "wiki.git_token",
  "wiki.export_default_view",
  "wiki.export_min_tier",
  "wiki.export_dir_naming",
] as const;

export const LLM_KEYS = [
  "llm.enabled",
  "llm.base_url",
  "llm.api_key",
  "llm.model",
  "llm.deep_search_model",
  "llm.max_concurrent",
  "llm.timeout",
  "llm.retry_count",
  "llm.temperature",
  "llm.enrichment_strategy",
  "llm.concept_extraction_enabled",
  "llm.business_flow_enabled",
] as const;

export const STORAGE_KEYS_LIST = [
  "falkordb.host",
  "falkordb.port",
  "falkordb.password",
  "falkordb.graph_name",
] as const;

export const EMBEDDING_KEYS = [
  "embedding.model_name",
  "embedding.dimension",
  "embedding.device",
  "embedding.backend",
  "embedding.batch_size",
  "embedding.use_fp16",
  "embedding.max_length",
] as const;

export const SYSTEM_KEYS_LIST = ["host", "port", "log_level", "rate_limit_rpm", "require_auth"] as const;

export const ALL_CONFIG_KEYS: string[] = [
  ...WIKI_FEATURES_KEYS,
  ...WIKI_GENERATION_KEYS,
  ...WIKI_PIPELINE_CONCURRENCY_KEYS,
  ...WIKI_DOMAIN_AGENT_KEYS,
  ...WIKI_COMPOSITION_KEYS,
  ...WIKI_REASSEMBLY_KEYS,
  ...WIKI_HEALING_QUALITY_KEYS,
  ...WIKI_DELEGATION_KEYS,
  ...WIKI_BUSINESS_DOMAIN_KEYS,
  ...WIKI_INCREMENTAL_BUDGET_KEYS,
  ...WIKI_GIT_KEYS,
  ...LLM_KEYS,
  ...STORAGE_KEYS_LIST,
  ...EMBEDDING_KEYS,
  ...SYSTEM_KEYS_LIST,
];

/** Keys edited as toggles; server may send Python-style "True"/"False". */
export const BOOL_KEYS = new Set<string>([
  ...WIKI_FEATURES_KEYS,
  "wiki.code_budget_enabled",
  "wiki.rag_enabled",
  "wiki.enrichment_enabled",
  "wiki.enrichment_round1_enabled",
  "wiki.enrichment_round2_enabled",
  "wiki.git_publish_enabled",
  "wiki.flow_compose_enabled",
  "wiki.guided_tour_enabled",
  "wiki.business_wiki_skip_repo_pages",
  "wiki.domain_reassembly_enabled",
  "wiki.reassembly_respect_user_modified",
  "wiki.heal_on_l3_failure",
  "wiki.quality_auto_heal",
  "wiki.delegation_enabled",
  "wiki.incremental_enabled",
  "wiki.resume_from_saved",
  "llm.enabled",
  "llm.concept_extraction_enabled",
  "llm.business_flow_enabled",
  "embedding.use_fp16",
  "require_auth",
]);

export type SettingMeta = { source: string; sensitive: boolean; category: string };

export type NumberFieldConstraint = { min: number; max: number };

/** Min/max bounds for number settings validated on save. */
export const NUMBER_FIELD_CONSTRAINTS: Record<string, NumberFieldConstraint> = {
  "wiki.compose_concurrency": { min: 1, max: 50 },
  "wiki.heal_concurrency": { min: 1, max: 20 },
  "wiki.domain_agent_concurrency": { min: 1, max: 10 },
  "wiki.module_compose_concurrency": { min: 1, max: 10 },
  "wiki.flow_compose_concurrency": { min: 1, max: 10 },
  "wiki.heal_max_rounds_core": { min: 1, max: 10 },
  "wiki.heal_max_rounds_standard": { min: 1, max: 5 },
  "wiki.llm_global_rpm_limit": { min: 0, max: 300 },
  "wiki.domain_split_threshold": { min: 5, max: 50 },
  "wiki.domain_split_max_depth": { min: 1, max: 5 },
  // Domain agent
  "wiki.domain_agent_max_iterations_core": { min: 1, max: 100 },
  "wiki.domain_agent_max_iterations_standard": { min: 1, max: 50 },
  "wiki.domain_agent_max_iterations_skeleton": { min: 1, max: 20 },
  "wiki.domain_agent_timeout_sec": { min: 60, max: 3600 },
  "wiki.domain_agent_explore_max_rounds": { min: 1, max: 20 },
  "wiki.domain_agent_explore_max_tool_calls": { min: 5, max: 100 },
  "wiki.domain_agent_early_exit_quality": { min: 0, max: 1 },
  "wiki.domain_agent_early_exit_min_chars": { min: 0, max: 5000 },
  // Reassembly
  "wiki.reassembly_merge_threshold": { min: 0.5, max: 1 },
  "wiki.embedding_merge_threshold": { min: 0.5, max: 1 },
  "wiki.reassembly_orphan_threshold": { min: 0.3, max: 1 },
  "wiki.reassembly_max_moves_pct": { min: 0, max: 1 },
  "wiki.consolidation_min_count": { min: 2, max: 20 },
  "wiki.consolidation_min_domains": { min: 2, max: 20 },
  // Healing & quality
  "wiki.heal_loop_max_total_attempts": { min: 1, max: 50 },
  "wiki.heal_l2_threshold": { min: 0, max: 1 },
  "wiki.heal_l3_threshold": { min: 0, max: 1 },
  "wiki.quality_min_score": { min: 0, max: 1 },
  "wiki.quality_sample_size": { min: 1, max: 100 },
  // Delegation
  "wiki.delegation_max_children": { min: 5, max: 100 },
  "wiki.delegation_max_code_lines": { min: 100, max: 50000 },
  // Business domain
  "wiki.business_domain_sub_batch_size": { min: 10, max: 200 },
  "wiki.business_domain_classify_timeout": { min: 60, max: 3600 },
  "wiki.business_domain_max_concurrency": { min: 1, max: 10 },
  "wiki.business_domain_cache_ttl": { min: 0, max: 86400 },
  // Incremental & budget
  "wiki.default_llm_budget": { min: 1000, max: 100000 },
  "wiki.core_code_budget": { min: 1000, max: 100000 },
  "wiki.standard_code_budget": { min: 1000, max: 50000 },
  "wiki.skeleton_code_budget": { min: 100, max: 10000 },
  "wiki.importance_core_percentile": { min: 50, max: 99 },
  "wiki.importance_standard_percentile": { min: 10, max: 80 },
};

export type NumberFieldValidationError =
  | { kind: "empty"; key: string }
  | { kind: "outOfRange"; key: string; min: number; max: number };

export function validateNumberFieldValue(key: string, value: string): NumberFieldValidationError | null {
  const constraint = NUMBER_FIELD_CONSTRAINTS[key];
  if (!constraint) return null;
  const trimmed = value.trim();
  if (trimmed === "") return { kind: "empty", key };
  const num = Number(trimmed);
  if (!Number.isFinite(num) || num < constraint.min || num > constraint.max) {
    return { kind: "outOfRange", key, min: constraint.min, max: constraint.max };
  }
  return null;
}

export function truthyString(s: string): boolean {
  const v = s.trim().toLowerCase();
  return v === "true" || v === "1" || v === "yes";
}

export function normalizeBoolValues(record: Record<string, string>): Record<string, string> {
  const out = { ...record };
  for (const k of BOOL_KEYS) {
    if (out[k] === undefined || out[k] === "") continue;
    out[k] = truthyString(out[k]) ? "true" : "false";
  }
  return out;
}

export function flattenCategories(categories: SettingsResponse["categories"]) {
  const values: Record<string, string> = {};
  const meta: Record<string, SettingMeta> = {};
  for (const [category, items] of Object.entries(categories)) {
    for (const [key, item] of Object.entries(items)) {
      values[key] = item.value;
      meta[key] = { source: item.source, sensitive: item.sensitive, category };
    }
  }
  return { values, meta };
}

export function mergeKeys(values: Record<string, string>): Record<string, string> {
  const normalized = normalizeBoolValues(values);
  const v = { ...normalized };
  for (const k of ALL_CONFIG_KEYS) {
    if (v[k] === undefined) v[k] = "";
  }
  return normalizeBoolValues(v);
}
