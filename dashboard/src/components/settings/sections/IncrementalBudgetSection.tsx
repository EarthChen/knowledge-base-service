import { PiggyBank } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

const SKELETON_STRATEGY_OPTIONS = [
  { value: "priority", label: "Priority" },
  { value: "round_robin", label: "Round-robin" },
];

export default function IncrementalBudgetSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard
      title={t.configSettings.incrementalBudgetTitle}
      icon={<PiggyBank size={18} className="text-sky-600" />}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SettingsToggle
            label={configFieldLabel("wiki.incremental_enabled", t)}
            checked={boolVal("wiki.incremental_enabled")}
            onChange={(v) => onChange("wiki.incremental_enabled", v ? "true" : "false")}
            source={sourceBadge("wiki.incremental_enabled", meta, t)}
          />
          <SettingsToggle
            label={configFieldLabel("wiki.resume_from_saved", t)}
            checked={boolVal("wiki.resume_from_saved")}
            onChange={(v) => onChange("wiki.resume_from_saved", v ? "true" : "false")}
            source={sourceBadge("wiki.resume_from_saved", meta, t)}
          />
        </div>
        <SettingsInput
          label={configFieldLabel("wiki.default_llm_budget", t)}
          type="number"
          min={1000}
          max={100000}
          value={values["wiki.default_llm_budget"] ?? ""}
          onChange={(v) => onChange("wiki.default_llm_budget", v)}
          source={sourceBadge("wiki.default_llm_budget", meta, t)}
        />
        <div className="border-t border-gray-200 pt-3 dark:border-gray-700">
          <SettingsToggle
            label={configFieldLabel("wiki.code_budget_enabled", t)}
            checked={boolVal("wiki.code_budget_enabled")}
            onChange={(v) => onChange("wiki.code_budget_enabled", v ? "true" : "false")}
            source={sourceBadge("wiki.code_budget_enabled", meta, t)}
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <SettingsInput
              label={configFieldLabel("wiki.core_code_budget", t)}
              type="number"
              min={1000}
              max={100000}
              value={values["wiki.core_code_budget"] ?? ""}
              onChange={(v) => onChange("wiki.core_code_budget", v)}
              source={sourceBadge("wiki.core_code_budget", meta, t)}
            />
            <SettingsInput
              label={configFieldLabel("wiki.standard_code_budget", t)}
              type="number"
              min={1000}
              max={50000}
              value={values["wiki.standard_code_budget"] ?? ""}
              onChange={(v) => onChange("wiki.standard_code_budget", v)}
              source={sourceBadge("wiki.standard_code_budget", meta, t)}
            />
            <SettingsInput
              label={configFieldLabel("wiki.skeleton_code_budget", t)}
              type="number"
              min={100}
              max={10000}
              value={values["wiki.skeleton_code_budget"] ?? ""}
              onChange={(v) => onChange("wiki.skeleton_code_budget", v)}
              source={sourceBadge("wiki.skeleton_code_budget", meta, t)}
            />
            <SettingsInput
              label={configFieldLabel("wiki.importance_core_percentile", t)}
              type="number"
              min={50}
              max={99}
              value={values["wiki.importance_core_percentile"] ?? ""}
              onChange={(v) => onChange("wiki.importance_core_percentile", v)}
              source={sourceBadge("wiki.importance_core_percentile", meta, t)}
            />
            <SettingsInput
              label={configFieldLabel("wiki.importance_standard_percentile", t)}
              type="number"
              min={10}
              max={80}
              value={values["wiki.importance_standard_percentile"] ?? ""}
              onChange={(v) => onChange("wiki.importance_standard_percentile", v)}
              source={sourceBadge("wiki.importance_standard_percentile", meta, t)}
            />
          </div>
        </div>
        <div className="border-t border-gray-200 pt-3 dark:border-gray-700">
          <SettingsSelect
            label={configFieldLabel("wiki.skeleton_strategy", t)}
            value={values["wiki.skeleton_strategy"] ?? ""}
            onChange={(v) => onChange("wiki.skeleton_strategy", v)}
            options={SKELETON_STRATEGY_OPTIONS}
            source={sourceBadge("wiki.skeleton_strategy", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.skeleton_light_model", t)}
            type="text"
            value={values["wiki.skeleton_light_model"] ?? ""}
            onChange={(v) => onChange("wiki.skeleton_light_model", v)}
            source={sourceBadge("wiki.skeleton_light_model", meta, t)}
          />
        </div>
      </div>
    </SettingsCard>
  );
}
