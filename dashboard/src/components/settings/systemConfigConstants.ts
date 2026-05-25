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
  "wiki.heal_max_rounds_core": { min: 0, max: 5 },
  "wiki.heal_max_rounds_standard": { min: 0, max: 5 },
  "wiki.llm_global_rpm_limit": { min: 0, max: 300 },
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
