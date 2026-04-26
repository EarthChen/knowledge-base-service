import { Bot, Loader2 } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSecretInput from "../SettingsSecretInput";
import SettingsToggle from "../SettingsToggle";
import type { ConnectionSectionProps } from "./types";

export default function LLMSection({
  values,
  meta,
  onChange,
  t,
  onTestConnection,
  testConnectionPending,
}: ConnectionSectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard title={t.configSettings.llmTitle} icon={<Bot size={18} className="text-sky-600" />}>
      <SettingsToggle
        label={configFieldLabel("llm.enabled", t)}
        checked={boolVal("llm.enabled")}
        onChange={(v) => onChange("llm.enabled", v ? "true" : "false")}
        source={sourceBadge("llm.enabled", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.base_url", t)}
        value={values["llm.base_url"] ?? ""}
        onChange={(v) => onChange("llm.base_url", v)}
        source={sourceBadge("llm.base_url", meta, t)}
      />
      <SettingsSecretInput
        label={configFieldLabel("llm.api_key", t)}
        value={values["llm.api_key"] ?? ""}
        onChange={(v) => onChange("llm.api_key", v)}
        source={sourceBadge("llm.api_key", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.model", t)}
        value={values["llm.model"] ?? ""}
        onChange={(v) => onChange("llm.model", v)}
        source={sourceBadge("llm.model", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.deep_search_model", t)}
        value={values["llm.deep_search_model"] ?? ""}
        onChange={(v) => onChange("llm.deep_search_model", v)}
        source={sourceBadge("llm.deep_search_model", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.max_concurrent", t)}
        type="number"
        value={values["llm.max_concurrent"] ?? ""}
        onChange={(v) => onChange("llm.max_concurrent", v)}
        source={sourceBadge("llm.max_concurrent", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.timeout", t)}
        type="number"
        value={values["llm.timeout"] ?? ""}
        onChange={(v) => onChange("llm.timeout", v)}
        source={sourceBadge("llm.timeout", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.retry_count", t)}
        type="number"
        value={values["llm.retry_count"] ?? ""}
        onChange={(v) => onChange("llm.retry_count", v)}
        source={sourceBadge("llm.retry_count", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.temperature", t)}
        type="number"
        value={values["llm.temperature"] ?? ""}
        onChange={(v) => onChange("llm.temperature", v)}
        source={sourceBadge("llm.temperature", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("llm.enrichment_strategy", t)}
        value={values["llm.enrichment_strategy"] ?? ""}
        onChange={(v) => onChange("llm.enrichment_strategy", v)}
        source={sourceBadge("llm.enrichment_strategy", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("llm.concept_extraction_enabled", t)}
        checked={boolVal("llm.concept_extraction_enabled")}
        onChange={(v) => onChange("llm.concept_extraction_enabled", v ? "true" : "false")}
        source={sourceBadge("llm.concept_extraction_enabled", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("llm.business_flow_enabled", t)}
        checked={boolVal("llm.business_flow_enabled")}
        onChange={(v) => onChange("llm.business_flow_enabled", v ? "true" : "false")}
        source={sourceBadge("llm.business_flow_enabled", meta, t)}
      />
      <div>
        <button
          type="button"
          disabled={testConnectionPending}
          onClick={() => onTestConnection("llm")}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
        >
          {testConnectionPending ? <Loader2 size={16} className="animate-spin" /> : null}
          {testConnectionPending ? t.configSettings.testing : t.configSettings.testConnection}
        </button>
      </div>
    </SettingsCard>
  );
}
