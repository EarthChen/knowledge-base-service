import type { Translations } from "../../i18n/types";

type Fields = Translations["configSettings"]["fields"];

const FIELD_KEYS: Partial<Record<string, keyof Fields>> = {
  "wiki.tree_enabled": "fieldTreeEnabled",
  "wiki.dual_view_enabled": "fieldDualViewEnabled",
  "wiki.cross_reference_enabled": "fieldCrossReferenceEnabled",
  "wiki.coverage_report_enabled": "fieldCoverageReportEnabled",
  "wiki.stale_detection_enabled": "fieldStaleDetectionEnabled",
  "wiki.suggested_questions_enabled": "fieldSuggestedQuestionsEnabled",
  "wiki.knowledge_injection_enabled": "fieldKnowledgeInjectionEnabled",
  "wiki.cross_repo_domain_enabled": "fieldCrossRepoDomainEnabled",
  "wiki.auto_update_on_index": "fieldAutoUpdateOnIndex",
  "wiki.mcp_server_enabled": "fieldMcpServerEnabled",
  "wiki.feedback_enabled": "fieldFeedbackEnabled",
  "wiki.lint_scheduler_enabled": "fieldLintSchedulerEnabled",
  "wiki.auto_heal_enabled": "fieldAutoHealEnabled",
  "wiki.deep_research_enabled": "fieldDeepResearchEnabled",
  "wiki.concept_merging_enabled": "fieldConceptMergingEnabled",
  "llm.concept_extraction_enabled": "fieldConceptExtractionEnabled",
  "llm.business_flow_enabled": "fieldBusinessFlowEnabled",
  "wiki.business_domain_enabled": "fieldBusinessDomainEnabled",
  "wiki.confidence_scoring_enabled": "fieldConfidenceScoringEnabled",
  "wiki.contradiction_detection_enabled": "fieldContradictionDetectionEnabled",
  "wiki.supersession_tracking_enabled": "fieldSupersessionTrackingEnabled",
  "wiki.memory_tiers_enabled": "fieldMemoryTiersEnabled",
  "wiki.forgetting_enabled": "fieldForgettingEnabled",
  "wiki.schema_validation_enabled": "fieldSchemaValidationEnabled",
  "wiki.code_budget_enabled": "fieldCodeBudgetEnabled",
  "wiki.rag_enabled": "fieldRagEnabled",
  "wiki.enrichment_enabled": "fieldEnrichmentEnabled",
  "wiki.git_publish_enabled": "fieldGitPublishEnabled",
  "llm.enabled": "fieldLlmEnabled",
  "embedding.use_fp16": "fieldUseFp16",
  require_auth: "fieldRequireAuth",
};

const OPTION_KEYS: Record<string, keyof Fields> = {
  incremental: "optionIncremental",
  full: "optionFull",
  manual: "optionManual",
  auto: "optionAutomatic",
  automatic: "optionAutomatic",
  disabled: "optionDisabled",
  core_only: "optionCoreOnly",
  business_domain: "optionBusinessDomain",
  code: "optionCodeStructure",
  original: "optionOriginal",
  kebab: "optionKebab",
};

export function humanizeKey(key: string): string {
  const part = key.includes(".") ? key.split(".").pop()! : key;
  return part.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function configFieldLabel(key: string, t: Translations): string {
  const fk = FIELD_KEYS[key];
  if (fk) return t.configSettings.fields[fk];
  return humanizeKey(key);
}

export function configOptionLabel(value: string, t: Translations): string {
  const k = OPTION_KEYS[value.trim().toLowerCase()];
  if (k) return t.configSettings.fields[k];
  return humanizeKey(value);
}

export function sourceBadge(
  key: string,
  meta: Record<string, { source: string; sensitive?: boolean } | undefined>,
  t: Translations,
): string | undefined {
  const s = meta[key]?.source;
  if (s === "db") return t.configSettings.fields.fieldSourceDb;
  if (s === "env") return t.configSettings.fields.fieldSourceEnv;
  if (s === "default") return t.configSettings.fields.fieldSourceDefault;
  return undefined;
}
