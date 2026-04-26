import { Layers } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function WikiGenerationSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard title={t.configSettings.wikiGenerationTitle} icon={<Layers size={18} className="text-sky-600" />}>
      <SettingsToggle
        label={configFieldLabel("wiki.code_budget_enabled", t)}
        checked={boolVal("wiki.code_budget_enabled")}
        onChange={(v) => onChange("wiki.code_budget_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.code_budget_enabled", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.core_code_budget", t)}
        type="number"
        value={values["wiki.core_code_budget"] ?? ""}
        onChange={(v) => onChange("wiki.core_code_budget", v)}
        source={sourceBadge("wiki.core_code_budget", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.standard_code_budget", t)}
        type="number"
        value={values["wiki.standard_code_budget"] ?? ""}
        onChange={(v) => onChange("wiki.standard_code_budget", v)}
        source={sourceBadge("wiki.standard_code_budget", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.skeleton_code_budget", t)}
        type="number"
        value={values["wiki.skeleton_code_budget"] ?? ""}
        onChange={(v) => onChange("wiki.skeleton_code_budget", v)}
        source={sourceBadge("wiki.skeleton_code_budget", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.importance_core_percentile", t)}
        type="number"
        value={values["wiki.importance_core_percentile"] ?? ""}
        onChange={(v) => onChange("wiki.importance_core_percentile", v)}
        source={sourceBadge("wiki.importance_core_percentile", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.importance_standard_percentile", t)}
        type="number"
        value={values["wiki.importance_standard_percentile"] ?? ""}
        onChange={(v) => onChange("wiki.importance_standard_percentile", v)}
        source={sourceBadge("wiki.importance_standard_percentile", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("wiki.rag_enabled", t)}
        checked={boolVal("wiki.rag_enabled")}
        onChange={(v) => onChange("wiki.rag_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.rag_enabled", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.rag_top_k", t)}
        type="number"
        value={values["wiki.rag_top_k"] ?? ""}
        onChange={(v) => onChange("wiki.rag_top_k", v)}
        source={sourceBadge("wiki.rag_top_k", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.rag_min_score", t)}
        type="number"
        value={values["wiki.rag_min_score"] ?? ""}
        onChange={(v) => onChange("wiki.rag_min_score", v)}
        source={sourceBadge("wiki.rag_min_score", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("wiki.enrichment_enabled", t)}
        checked={boolVal("wiki.enrichment_enabled")}
        onChange={(v) => onChange("wiki.enrichment_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.enrichment_enabled", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("wiki.enrichment_round1_enabled", t)}
        checked={boolVal("wiki.enrichment_round1_enabled")}
        onChange={(v) => onChange("wiki.enrichment_round1_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.enrichment_round1_enabled", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("wiki.enrichment_round2_enabled", t)}
        checked={boolVal("wiki.enrichment_round2_enabled")}
        onChange={(v) => onChange("wiki.enrichment_round2_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.enrichment_round2_enabled", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("wiki.cot_enabled", t)}
        checked={boolVal("wiki.cot_enabled")}
        onChange={(v) => onChange("wiki.cot_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.cot_enabled", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.cot_analysis_model", t)}
        value={values["wiki.cot_analysis_model"] ?? ""}
        onChange={(v) => onChange("wiki.cot_analysis_model", v)}
        source={sourceBadge("wiki.cot_analysis_model", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.cot_generation_model", t)}
        value={values["wiki.cot_generation_model"] ?? ""}
        onChange={(v) => onChange("wiki.cot_generation_model", v)}
        source={sourceBadge("wiki.cot_generation_model", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.business_wiki_batch_threshold", t)}
        type="number"
        value={values["wiki.business_wiki_batch_threshold"] ?? ""}
        onChange={(v) => onChange("wiki.business_wiki_batch_threshold", v)}
        source={sourceBadge("wiki.business_wiki_batch_threshold", meta, t)}
      />
    </SettingsCard>
  );
}
