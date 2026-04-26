import { useEffect, useMemo, useRef, useState } from "react";
import {
  BookOpen,
  Bot,
  Box,
  Database,
  GitBranch,
  Layers,
  Loader2,
  Server,
} from "lucide-react";
import { useAllSettings } from "../../hooks/useSettings";
import { useTestConnection, useUpdateSettings } from "../../hooks/useUpdateSettings";
import { getSettingCategory } from "../../hooks/settingsCategory";
import type { SettingsResponse } from "../../hooks/settingsTypes";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import { useToast } from "../Toast";
import { SkeletonLine } from "../Skeleton";
import SettingsCard from "./SettingsCard";
import SettingsInput from "./SettingsInput";
import SettingsSecretInput from "./SettingsSecretInput";
import SettingsSelect from "./SettingsSelect";
import SettingsToggle from "./SettingsToggle";

const WIKI_FEATURES_KEYS = [
  "wiki.tree_enabled",
  "wiki.dual_view_enabled",
  "wiki.cross_reference_enabled",
  "wiki.coverage_report_enabled",
  "wiki.stale_detection_enabled",
  "wiki.suggested_questions_enabled",
  "wiki.knowledge_injection_enabled",
  "wiki.cross_repo_domain_enabled",
  "wiki.auto_update_on_index",
] as const;

const WIKI_GENERATION_KEYS = [
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
  "wiki.cot_enabled",
  "wiki.cot_analysis_model",
  "wiki.cot_generation_model",
  "wiki.business_wiki_batch_threshold",
] as const;

const WIKI_GIT_KEYS = [
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

const LLM_KEYS = [
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
] as const;

const STORAGE_KEYS_LIST = [
  "falkordb.host",
  "falkordb.port",
  "falkordb.password",
  "falkordb.graph_name",
] as const;

const EMBEDDING_KEYS = [
  "embedding.model_name",
  "embedding.dimension",
  "embedding.device",
  "embedding.backend",
  "embedding.batch_size",
  "embedding.use_fp16",
  "embedding.max_length",
] as const;

const SYSTEM_KEYS_LIST = [
  "host",
  "port",
  "log_level",
  "rate_limit_rpm",
  "require_auth",
] as const;

const ALL_CONFIG_KEYS: string[] = [
  ...WIKI_FEATURES_KEYS,
  ...WIKI_GENERATION_KEYS,
  ...WIKI_GIT_KEYS,
  ...LLM_KEYS,
  ...STORAGE_KEYS_LIST,
  ...EMBEDDING_KEYS,
  ...SYSTEM_KEYS_LIST,
];

/** Keys edited as toggles; server may send Python-style "True"/"False". */
const BOOL_KEYS = new Set<string>([
  ...WIKI_FEATURES_KEYS,
  "wiki.code_budget_enabled",
  "wiki.rag_enabled",
  "wiki.enrichment_enabled",
  "wiki.enrichment_round1_enabled",
  "wiki.enrichment_round2_enabled",
  "wiki.cot_enabled",
  "wiki.git_publish_enabled",
  "llm.enabled",
  "embedding.use_fp16",
  "require_auth",
]);

function truthyString(s: string): boolean {
  const v = s.trim().toLowerCase();
  return v === "true" || v === "1" || v === "yes";
}

function normalizeBoolValues(record: Record<string, string>): Record<string, string> {
  const out = { ...record };
  for (const k of BOOL_KEYS) {
    if (out[k] === undefined || out[k] === "") continue;
    out[k] = truthyString(out[k]) ? "true" : "false";
  }
  return out;
}

type SettingMeta = { source: string; sensitive: boolean; category: string };

function flattenCategories(categories: SettingsResponse["categories"]) {
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

function mergeKeys(values: Record<string, string>): Record<string, string> {
  const normalized = normalizeBoolValues(values);
  const v = { ...normalized };
  for (const k of ALL_CONFIG_KEYS) {
    if (v[k] === undefined) v[k] = "";
  }
  return normalizeBoolValues(v);
}

function humanizeKey(key: string): string {
  const part = key.includes(".") ? key.split(".").pop()! : key;
  return part.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function SystemConfigPanel() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { data, isLoading, error, refetch } = useAllSettings();
  const updateSettings = useUpdateSettings();
  const testConnection = useTestConnection();

  const mergedFlat = useMemo(() => {
    if (!data?.categories) return null;
    return flattenCategories(data.categories);
  }, [data]);

  const [values, setValues] = useState<Record<string, string>>({});
  const [baseline, setBaseline] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState<Record<string, SettingMeta>>({});
  const didInit = useRef(false);

  useEffect(() => {
    return () => {
      didInit.current = false;
    };
  }, []);

  useEffect(() => {
    if (!mergedFlat) return;
    if (!didInit.current) {
      setValues(mergeKeys(mergedFlat.values));
      setBaseline(mergeKeys(mergedFlat.values));
      setMeta(mergedFlat.meta);
      didInit.current = true;
    }
  }, [mergedFlat]);

  const dirtyKeys = useMemo(
    () => Object.keys(values).filter((k) => values[k] !== baseline[k]),
    [values, baseline],
  );
  const dirtyCount = dirtyKeys.length;

  const sourceBadge = (key: string) => {
    const s = meta[key]?.source;
    if (s === "db") return t.configSettings.sourceDb;
    if (s === "env") return t.configSettings.sourceEnv;
    if (s === "default") return t.configSettings.sourceDefault;
    return undefined;
  };

  const setVal = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const boolVal = (key: string) => values[key] === "true";

  async function handleSave() {
    if (dirtyCount === 0) return;
    const updates = dirtyKeys.map((key) => ({
      key,
      value: values[key],
      category: meta[key]?.category ?? getSettingCategory(key),
    }));
    try {
      await updateSettings.mutateAsync({ settings: updates });
      const res = await refetch();
      if (res.data?.categories) {
        const flat = flattenCategories(res.data.categories);
        setMeta(flat.meta);
        setValues(mergeKeys(flat.values));
        setBaseline(mergeKeys(flat.values));
      }
      toast("success", t.configSettings.saved);
    } catch (e) {
      toast("error", getErrorMessage(e) || t.configSettings.saveFailed);
    }
  }

  async function runTest(target: string) {
    try {
      const r = await testConnection.mutateAsync(target);
      if (r.status === "ok") {
        toast("success", `${t.configSettings.connectionOk}: ${r.message}`);
      } else {
        toast("error", `${t.configSettings.connectionFailed}: ${r.message}`);
      }
    } catch (e) {
      toast("error", getErrorMessage(e) || t.configSettings.connectionFailed);
    }
  }

  if (isLoading && !data) {
    return (
      <div className="space-y-4">
        <SkeletonLine className="h-10 w-full max-w-md" />
        <SkeletonLine className="h-40 w-full" />
        <SkeletonLine className="h-40 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
        {getErrorMessage(error)}
      </div>
    );
  }

  return (
    <div className="relative space-y-6 pb-24">
      <SettingsCard title={t.configSettings.wikiFeaturesTitle} icon={<BookOpen size={18} className="text-sky-600" />}>
        {WIKI_FEATURES_KEYS.map((key) => (
          <SettingsToggle
            key={key}
            label={humanizeKey(key)}
            checked={boolVal(key)}
            onChange={(v) => setVal(key, v ? "true" : "false")}
            source={sourceBadge(key)}
          />
        ))}
      </SettingsCard>

      <SettingsCard
        title={t.configSettings.wikiGenerationTitle}
        icon={<Layers size={18} className="text-sky-600" />}
      >
        <SettingsToggle
          label={humanizeKey("wiki.code_budget_enabled")}
          checked={boolVal("wiki.code_budget_enabled")}
          onChange={(v) => setVal("wiki.code_budget_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.code_budget_enabled")}
        />
        <SettingsInput
          label={humanizeKey("wiki.core_code_budget")}
          type="number"
          value={values["wiki.core_code_budget"] ?? ""}
          onChange={(v) => setVal("wiki.core_code_budget", v)}
          source={sourceBadge("wiki.core_code_budget")}
        />
        <SettingsInput
          label={humanizeKey("wiki.standard_code_budget")}
          type="number"
          value={values["wiki.standard_code_budget"] ?? ""}
          onChange={(v) => setVal("wiki.standard_code_budget", v)}
          source={sourceBadge("wiki.standard_code_budget")}
        />
        <SettingsInput
          label={humanizeKey("wiki.skeleton_code_budget")}
          type="number"
          value={values["wiki.skeleton_code_budget"] ?? ""}
          onChange={(v) => setVal("wiki.skeleton_code_budget", v)}
          source={sourceBadge("wiki.skeleton_code_budget")}
        />
        <SettingsInput
          label={humanizeKey("wiki.importance_core_percentile")}
          type="number"
          value={values["wiki.importance_core_percentile"] ?? ""}
          onChange={(v) => setVal("wiki.importance_core_percentile", v)}
          source={sourceBadge("wiki.importance_core_percentile")}
        />
        <SettingsInput
          label={humanizeKey("wiki.importance_standard_percentile")}
          type="number"
          value={values["wiki.importance_standard_percentile"] ?? ""}
          onChange={(v) => setVal("wiki.importance_standard_percentile", v)}
          source={sourceBadge("wiki.importance_standard_percentile")}
        />
        <SettingsToggle
          label={humanizeKey("wiki.rag_enabled")}
          checked={boolVal("wiki.rag_enabled")}
          onChange={(v) => setVal("wiki.rag_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.rag_enabled")}
        />
        <SettingsInput
          label={humanizeKey("wiki.rag_top_k")}
          type="number"
          value={values["wiki.rag_top_k"] ?? ""}
          onChange={(v) => setVal("wiki.rag_top_k", v)}
          source={sourceBadge("wiki.rag_top_k")}
        />
        <SettingsInput
          label={humanizeKey("wiki.rag_min_score")}
          type="number"
          value={values["wiki.rag_min_score"] ?? ""}
          onChange={(v) => setVal("wiki.rag_min_score", v)}
          source={sourceBadge("wiki.rag_min_score")}
        />
        <SettingsToggle
          label={humanizeKey("wiki.enrichment_enabled")}
          checked={boolVal("wiki.enrichment_enabled")}
          onChange={(v) => setVal("wiki.enrichment_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.enrichment_enabled")}
        />
        <SettingsToggle
          label={humanizeKey("wiki.enrichment_round1_enabled")}
          checked={boolVal("wiki.enrichment_round1_enabled")}
          onChange={(v) => setVal("wiki.enrichment_round1_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.enrichment_round1_enabled")}
        />
        <SettingsToggle
          label={humanizeKey("wiki.enrichment_round2_enabled")}
          checked={boolVal("wiki.enrichment_round2_enabled")}
          onChange={(v) => setVal("wiki.enrichment_round2_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.enrichment_round2_enabled")}
        />
        <SettingsToggle
          label={humanizeKey("wiki.cot_enabled")}
          checked={boolVal("wiki.cot_enabled")}
          onChange={(v) => setVal("wiki.cot_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.cot_enabled")}
        />
        <SettingsInput
          label={humanizeKey("wiki.cot_analysis_model")}
          value={values["wiki.cot_analysis_model"] ?? ""}
          onChange={(v) => setVal("wiki.cot_analysis_model", v)}
          source={sourceBadge("wiki.cot_analysis_model")}
        />
        <SettingsInput
          label={humanizeKey("wiki.cot_generation_model")}
          value={values["wiki.cot_generation_model"] ?? ""}
          onChange={(v) => setVal("wiki.cot_generation_model", v)}
          source={sourceBadge("wiki.cot_generation_model")}
        />
        <SettingsInput
          label={humanizeKey("wiki.business_wiki_batch_threshold")}
          type="number"
          value={values["wiki.business_wiki_batch_threshold"] ?? ""}
          onChange={(v) => setVal("wiki.business_wiki_batch_threshold", v)}
          source={sourceBadge("wiki.business_wiki_batch_threshold")}
        />
      </SettingsCard>

      <SettingsCard title={t.configSettings.wikiGitTitle} icon={<GitBranch size={18} className="text-sky-600" />}>
        <SettingsToggle
          label={humanizeKey("wiki.git_publish_enabled")}
          checked={boolVal("wiki.git_publish_enabled")}
          onChange={(v) => setVal("wiki.git_publish_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.git_publish_enabled")}
        />
        <SettingsSelect
          label={humanizeKey("wiki.git_publish_mode")}
          value={values["wiki.git_publish_mode"] || "incremental"}
          onChange={(v) => setVal("wiki.git_publish_mode", v)}
          source={sourceBadge("wiki.git_publish_mode")}
          options={[
            { value: "incremental", label: "incremental" },
            { value: "full", label: "full" },
          ]}
        />
        <SettingsSelect
          label={humanizeKey("wiki.git_publish_trigger")}
          value={values["wiki.git_publish_trigger"] || "manual"}
          onChange={(v) => setVal("wiki.git_publish_trigger", v)}
          source={sourceBadge("wiki.git_publish_trigger")}
          options={[
            { value: "manual", label: "manual" },
            { value: "schedule", label: "schedule" },
            { value: "webhook", label: "webhook" },
          ]}
        />
        <SettingsInput
          label={humanizeKey("wiki.git_remote_url")}
          value={values["wiki.git_remote_url"] ?? ""}
          onChange={(v) => setVal("wiki.git_remote_url", v)}
          source={sourceBadge("wiki.git_remote_url")}
        />
        <SettingsInput
          label={humanizeKey("wiki.git_branch")}
          value={values["wiki.git_branch"] ?? ""}
          onChange={(v) => setVal("wiki.git_branch", v)}
          source={sourceBadge("wiki.git_branch")}
        />
        <SettingsInput
          label={humanizeKey("wiki.git_author_name")}
          value={values["wiki.git_author_name"] ?? ""}
          onChange={(v) => setVal("wiki.git_author_name", v)}
          source={sourceBadge("wiki.git_author_name")}
        />
        <SettingsInput
          label={humanizeKey("wiki.git_author_email")}
          value={values["wiki.git_author_email"] ?? ""}
          onChange={(v) => setVal("wiki.git_author_email", v)}
          source={sourceBadge("wiki.git_author_email")}
        />
        <SettingsSecretInput
          label={humanizeKey("wiki.git_token")}
          value={values["wiki.git_token"] ?? ""}
          onChange={(v) => setVal("wiki.git_token", v)}
          source={sourceBadge("wiki.git_token")}
        />
        <SettingsSelect
          label={humanizeKey("wiki.export_default_view")}
          value={values["wiki.export_default_view"] || "business_domain"}
          onChange={(v) => setVal("wiki.export_default_view", v)}
          source={sourceBadge("wiki.export_default_view")}
          options={[
            { value: "business_domain", label: "business_domain" },
            { value: "code", label: "code" },
          ]}
        />
        <SettingsSelect
          label={humanizeKey("wiki.export_min_tier")}
          value={values["wiki.export_min_tier"] || "standard"}
          onChange={(v) => setVal("wiki.export_min_tier", v)}
          source={sourceBadge("wiki.export_min_tier")}
          options={[
            { value: "standard", label: "standard" },
            { value: "core", label: "core" },
            { value: "skeleton", label: "skeleton" },
          ]}
        />
        <SettingsSelect
          label={humanizeKey("wiki.export_dir_naming")}
          value={values["wiki.export_dir_naming"] || "original"}
          onChange={(v) => setVal("wiki.export_dir_naming", v)}
          source={sourceBadge("wiki.export_dir_naming")}
          options={[
            { value: "original", label: "original" },
            { value: "flat", label: "flat" },
          ]}
        />
      </SettingsCard>

      <SettingsCard title={t.configSettings.llmTitle} icon={<Bot size={18} className="text-sky-600" />}>
        <SettingsToggle
          label={humanizeKey("llm.enabled")}
          checked={boolVal("llm.enabled")}
          onChange={(v) => setVal("llm.enabled", v ? "true" : "false")}
          source={sourceBadge("llm.enabled")}
        />
        <SettingsInput
          label={humanizeKey("llm.base_url")}
          value={values["llm.base_url"] ?? ""}
          onChange={(v) => setVal("llm.base_url", v)}
          source={sourceBadge("llm.base_url")}
        />
        <SettingsSecretInput
          label={humanizeKey("llm.api_key")}
          value={values["llm.api_key"] ?? ""}
          onChange={(v) => setVal("llm.api_key", v)}
          source={sourceBadge("llm.api_key")}
        />
        <SettingsInput
          label={humanizeKey("llm.model")}
          value={values["llm.model"] ?? ""}
          onChange={(v) => setVal("llm.model", v)}
          source={sourceBadge("llm.model")}
        />
        <SettingsInput
          label={humanizeKey("llm.deep_search_model")}
          value={values["llm.deep_search_model"] ?? ""}
          onChange={(v) => setVal("llm.deep_search_model", v)}
          source={sourceBadge("llm.deep_search_model")}
        />
        <SettingsInput
          label={humanizeKey("llm.max_concurrent")}
          type="number"
          value={values["llm.max_concurrent"] ?? ""}
          onChange={(v) => setVal("llm.max_concurrent", v)}
          source={sourceBadge("llm.max_concurrent")}
        />
        <SettingsInput
          label={humanizeKey("llm.timeout")}
          type="number"
          value={values["llm.timeout"] ?? ""}
          onChange={(v) => setVal("llm.timeout", v)}
          source={sourceBadge("llm.timeout")}
        />
        <SettingsInput
          label={humanizeKey("llm.retry_count")}
          type="number"
          value={values["llm.retry_count"] ?? ""}
          onChange={(v) => setVal("llm.retry_count", v)}
          source={sourceBadge("llm.retry_count")}
        />
        <SettingsInput
          label={humanizeKey("llm.temperature")}
          type="number"
          value={values["llm.temperature"] ?? ""}
          onChange={(v) => setVal("llm.temperature", v)}
          source={sourceBadge("llm.temperature")}
        />
        <SettingsInput
          label={humanizeKey("llm.enrichment_strategy")}
          value={values["llm.enrichment_strategy"] ?? ""}
          onChange={(v) => setVal("llm.enrichment_strategy", v)}
          source={sourceBadge("llm.enrichment_strategy")}
        />
        <div>
          <button
            type="button"
            disabled={testConnection.isPending}
            onClick={() => runTest("llm")}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            {testConnection.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            {testConnection.isPending ? t.configSettings.testing : t.configSettings.testConnection}
          </button>
        </div>
      </SettingsCard>

      <SettingsCard title={t.configSettings.storageTitle} icon={<Database size={18} className="text-sky-600" />}>
        <SettingsInput
          label={humanizeKey("falkordb.host")}
          value={values["falkordb.host"] ?? ""}
          onChange={(v) => setVal("falkordb.host", v)}
          source={sourceBadge("falkordb.host")}
        />
        <SettingsInput
          label={humanizeKey("falkordb.port")}
          type="number"
          value={values["falkordb.port"] ?? ""}
          onChange={(v) => setVal("falkordb.port", v)}
          source={sourceBadge("falkordb.port")}
        />
        <SettingsSecretInput
          label={humanizeKey("falkordb.password")}
          value={values["falkordb.password"] ?? ""}
          onChange={(v) => setVal("falkordb.password", v)}
          source={sourceBadge("falkordb.password")}
        />
        <SettingsInput
          label={humanizeKey("falkordb.graph_name")}
          value={values["falkordb.graph_name"] ?? ""}
          onChange={(v) => setVal("falkordb.graph_name", v)}
          source={sourceBadge("falkordb.graph_name")}
        />
        <div>
          <button
            type="button"
            disabled={testConnection.isPending}
            onClick={() => runTest("falkordb")}
            className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
          >
            {testConnection.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            {testConnection.isPending ? t.configSettings.testing : t.configSettings.testConnection}
          </button>
        </div>
      </SettingsCard>

      <SettingsCard title={t.configSettings.embeddingTitle} icon={<Box size={18} className="text-sky-600" />}>
        <SettingsInput
          label={humanizeKey("embedding.model_name")}
          value={values["embedding.model_name"] ?? ""}
          onChange={(v) => setVal("embedding.model_name", v)}
          source={sourceBadge("embedding.model_name")}
        />
        <SettingsInput
          label={humanizeKey("embedding.dimension")}
          type="number"
          value={values["embedding.dimension"] ?? ""}
          onChange={(v) => setVal("embedding.dimension", v)}
          source={sourceBadge("embedding.dimension")}
        />
        <SettingsSelect
          label={humanizeKey("embedding.device")}
          value={values["embedding.device"] || "auto"}
          onChange={(v) => setVal("embedding.device", v)}
          source={sourceBadge("embedding.device")}
          options={[
            { value: "auto", label: "auto" },
            { value: "cpu", label: "cpu" },
            { value: "cuda", label: "cuda" },
            { value: "mps", label: "mps" },
          ]}
        />
        <SettingsSelect
          label={humanizeKey("embedding.backend")}
          value={values["embedding.backend"] || "onnx"}
          onChange={(v) => setVal("embedding.backend", v)}
          source={sourceBadge("embedding.backend")}
          options={[
            { value: "onnx", label: "onnx" },
            { value: "torch", label: "torch" },
            { value: "auto", label: "auto" },
          ]}
        />
        <SettingsInput
          label={humanizeKey("embedding.batch_size")}
          type="number"
          value={values["embedding.batch_size"] ?? ""}
          onChange={(v) => setVal("embedding.batch_size", v)}
          source={sourceBadge("embedding.batch_size")}
        />
        <SettingsToggle
          label={humanizeKey("embedding.use_fp16")}
          checked={boolVal("embedding.use_fp16")}
          onChange={(v) => setVal("embedding.use_fp16", v ? "true" : "false")}
          source={sourceBadge("embedding.use_fp16")}
        />
        <SettingsInput
          label={humanizeKey("embedding.max_length")}
          type="number"
          value={values["embedding.max_length"] ?? ""}
          onChange={(v) => setVal("embedding.max_length", v)}
          source={sourceBadge("embedding.max_length")}
        />
      </SettingsCard>

      <SettingsCard title={t.configSettings.systemTitle} icon={<Server size={18} className="text-sky-600" />}>
        <SettingsInput
          label={humanizeKey("host")}
          value={values.host ?? ""}
          onChange={(v) => setVal("host", v)}
          source={sourceBadge("host")}
        />
        <SettingsInput
          label={humanizeKey("port")}
          type="number"
          value={values.port ?? ""}
          onChange={(v) => setVal("port", v)}
          source={sourceBadge("port")}
        />
        <SettingsSelect
          label={humanizeKey("log_level")}
          value={(values.log_level || "INFO").toUpperCase()}
          onChange={(v) => setVal("log_level", v)}
          source={sourceBadge("log_level")}
          options={[
            { value: "DEBUG", label: "DEBUG" },
            { value: "INFO", label: "INFO" },
            { value: "WARNING", label: "WARNING" },
            { value: "ERROR", label: "ERROR" },
          ]}
        />
        <SettingsInput
          label={humanizeKey("rate_limit_rpm")}
          type="number"
          value={values.rate_limit_rpm ?? ""}
          onChange={(v) => setVal("rate_limit_rpm", v)}
          source={sourceBadge("rate_limit_rpm")}
        />
        <SettingsToggle
          label={humanizeKey("require_auth")}
          checked={boolVal("require_auth")}
          onChange={(v) => setVal("require_auth", v ? "true" : "false")}
          source={sourceBadge("require_auth")}
        />
      </SettingsCard>

      {dirtyCount > 0 && (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 flex-col items-center gap-2 sm:flex-row">
          <span className="rounded-full bg-gray-900/90 px-3 py-1 text-xs text-white shadow-lg dark:bg-gray-100 dark:text-gray-900">
            {t.configSettings.unsavedChanges.replace("{count}", String(dirtyCount))}
          </span>
          <button
            type="button"
            disabled={updateSettings.isPending}
            onClick={handleSave}
            className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-sky-500 disabled:opacity-50"
          >
            {updateSettings.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            {updateSettings.isPending ? t.configSettings.saving : `${t.configSettings.saveChanges} (${dirtyCount})`}
          </button>
        </div>
      )}
    </div>
  );
}
