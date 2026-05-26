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
  "wiki.compose_concurrency": "fieldComposeConcurrency",
  "wiki.heal_concurrency": "fieldHealConcurrency",
  "wiki.domain_agent_concurrency": "fieldDomainAgentConcurrency",
  "wiki.module_compose_concurrency": "fieldModuleComposeConcurrency",
  "wiki.flow_compose_concurrency": "fieldFlowComposeConcurrency",
  "wiki.heal_max_rounds_core": "fieldHealMaxRoundsCore",
  "wiki.heal_max_rounds_standard": "fieldHealMaxRoundsStandard",
  "wiki.llm_global_rpm_limit": "fieldLlmGlobalRpmLimit",
  "wiki.domain_split_threshold": "fieldDomainSplitThreshold",
  "wiki.domain_split_max_depth": "fieldDomainSplitMaxDepth",
  "wiki.rag_enabled": "fieldRagEnabled",
  "wiki.enrichment_enabled": "fieldEnrichmentEnabled",
  "wiki.enrichment_round1_enabled": "fieldEnrichmentRound1Enabled",
  "wiki.enrichment_round2_enabled": "fieldEnrichmentRound2Enabled",
  "wiki.git_publish_enabled": "fieldGitPublishEnabled",
  // Domain agent
  "wiki.domain_agent_max_iterations_core": "fieldDomainAgentMaxIterationsCore",
  "wiki.domain_agent_max_iterations_standard": "fieldDomainAgentMaxIterationsStandard",
  "wiki.domain_agent_max_iterations_skeleton": "fieldDomainAgentMaxIterationsSkeleton",
  "wiki.domain_agent_timeout_sec": "fieldDomainAgentTimeoutSec",
  "wiki.domain_agent_explore_max_rounds": "fieldDomainAgentExploreMaxRounds",
  "wiki.domain_agent_explore_max_tool_calls": "fieldDomainAgentExploreMaxToolCalls",
  "wiki.domain_agent_early_exit_quality": "fieldDomainAgentEarlyExitQuality",
  "wiki.domain_agent_early_exit_min_chars": "fieldDomainAgentEarlyExitMinChars",
  // Composition
  "wiki.wiki_content_language": "fieldWikiContentLanguage",
  "wiki.flow_compose_enabled": "fieldFlowComposeEnabled",
  "wiki.guided_tour_enabled": "fieldGuidedTourEnabled",
  "wiki.business_wiki_skip_repo_pages": "fieldBusinessWikiSkipRepoPages",
  // Reassembly
  "wiki.domain_reassembly_enabled": "fieldDomainReassemblyEnabled",
  "wiki.reassembly_merge_threshold": "fieldReassemblyMergeThreshold",
  "wiki.embedding_merge_threshold": "fieldEmbeddingMergeThreshold",
  "wiki.reassembly_orphan_threshold": "fieldReassemblyOrphanThreshold",
  "wiki.reassembly_max_moves_pct": "fieldReassemblyMaxMovesPct",
  "wiki.reassembly_respect_user_modified": "fieldReassemblyRespectUserModified",
  "wiki.consolidation_min_count": "fieldConsolidationMinCount",
  "wiki.consolidation_min_domains": "fieldConsolidationMinDomains",
  // Healing & quality
  "wiki.heal_loop_max_total_attempts": "fieldHealLoopMaxTotalAttempts",
  "wiki.heal_l2_threshold": "fieldHealL2Threshold",
  "wiki.heal_on_l3_failure": "fieldHealOnL3Failure",
  "wiki.heal_l3_threshold": "fieldHealL3Threshold",
  "wiki.quality_evaluation_mode": "fieldQualityEvaluationMode",
  "wiki.quality_min_score": "fieldQualityMinScore",
  "wiki.quality_auto_heal": "fieldQualityAutoHeal",
  "wiki.quality_judge_model": "fieldQualityJudgeModel",
  "wiki.quality_sample_size": "fieldQualitySampleSize",
  // Delegation
  "wiki.delegation_enabled": "fieldDelegationEnabled",
  "wiki.delegation_max_children": "fieldDelegationMaxChildren",
  "wiki.delegation_max_code_lines": "fieldDelegationMaxCodeLines",
  "wiki.delegation_grouping_strategy": "fieldDelegationGroupingStrategy",
  // Business domain
  "wiki.business_domain_sub_batch_size": "fieldBusinessDomainSubBatchSize",
  "wiki.business_domain_classify_timeout": "fieldBusinessDomainClassifyTimeout",
  "wiki.business_domain_max_concurrency": "fieldBusinessDomainMaxConcurrency",
  "wiki.business_domain_cache_ttl": "fieldBusinessDomainCacheTtl",
  // Incremental & budget
  "wiki.incremental_enabled": "fieldIncrementalEnabled",
  "wiki.resume_from_saved": "fieldResumeFromSaved",
  "wiki.default_llm_budget": "fieldDefaultLlmBudget",
  "wiki.skeleton_strategy": "fieldSkeletonStrategy",
  "wiki.skeleton_light_model": "fieldSkeletonLightModel",
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
  // Quality evaluation mode
  heuristic: "optionHeuristic",
  llm: "optionLlm",
  hybrid: "optionHybrid",
  // Delegation grouping strategy
  flat: "optionFlat",
  hierarchical: "optionHierarchical",
  // Skeleton strategy
  priority: "optionPriority",
  round_robin: "optionRoundRobin",
  // Content language
  en: "optionLangEn",
  zh: "optionLangZh",
  auto_lang: "optionLangAuto",
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
