import { ShieldCheck } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

const EVAL_MODE_OPTIONS = [
  { value: "heuristic", label: "Heuristic" },
  { value: "llm", label: "LLM" },
  { value: "hybrid", label: "Hybrid" },
];

export default function HealingQualitySection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard
      title={t.configSettings.healingQualityTitle}
      icon={<ShieldCheck size={18} className="text-sky-600" />}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SettingsInput
            label={configFieldLabel("wiki.heal_max_rounds_core", t)}
            type="number"
            min={1}
            max={10}
            value={values["wiki.heal_max_rounds_core"] ?? ""}
            onChange={(v) => onChange("wiki.heal_max_rounds_core", v)}
            source={sourceBadge("wiki.heal_max_rounds_core", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.heal_max_rounds_standard", t)}
            type="number"
            min={1}
            max={5}
            value={values["wiki.heal_max_rounds_standard"] ?? ""}
            onChange={(v) => onChange("wiki.heal_max_rounds_standard", v)}
            source={sourceBadge("wiki.heal_max_rounds_standard", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.heal_loop_max_total_attempts", t)}
            type="number"
            min={1}
            max={50}
            value={values["wiki.heal_loop_max_total_attempts"] ?? ""}
            onChange={(v) => onChange("wiki.heal_loop_max_total_attempts", v)}
            source={sourceBadge("wiki.heal_loop_max_total_attempts", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.heal_l2_threshold", t)}
            type="number"
            min={0}
            max={1}
            value={values["wiki.heal_l2_threshold"] ?? ""}
            onChange={(v) => onChange("wiki.heal_l2_threshold", v)}
            source={sourceBadge("wiki.heal_l2_threshold", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.heal_l3_threshold", t)}
            type="number"
            min={0}
            max={1}
            value={values["wiki.heal_l3_threshold"] ?? ""}
            onChange={(v) => onChange("wiki.heal_l3_threshold", v)}
            source={sourceBadge("wiki.heal_l3_threshold", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.quality_sample_size", t)}
            type="number"
            min={1}
            max={100}
            value={values["wiki.quality_sample_size"] ?? ""}
            onChange={(v) => onChange("wiki.quality_sample_size", v)}
            source={sourceBadge("wiki.quality_sample_size", meta, t)}
          />
        </div>
        <SettingsToggle
          label={configFieldLabel("wiki.heal_on_l3_failure", t)}
          checked={boolVal("wiki.heal_on_l3_failure")}
          onChange={(v) => onChange("wiki.heal_on_l3_failure", v ? "true" : "false")}
          source={sourceBadge("wiki.heal_on_l3_failure", meta, t)}
        />
        <SettingsSelect
          label={configFieldLabel("wiki.quality_evaluation_mode", t)}
          value={values["wiki.quality_evaluation_mode"] ?? ""}
          onChange={(v) => onChange("wiki.quality_evaluation_mode", v)}
          options={EVAL_MODE_OPTIONS}
          source={sourceBadge("wiki.quality_evaluation_mode", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.quality_min_score", t)}
          type="number"
          min={0}
          max={1}
          value={values["wiki.quality_min_score"] ?? ""}
          onChange={(v) => onChange("wiki.quality_min_score", v)}
          source={sourceBadge("wiki.quality_min_score", meta, t)}
        />
        <SettingsToggle
          label={configFieldLabel("wiki.quality_auto_heal", t)}
          checked={boolVal("wiki.quality_auto_heal")}
          onChange={(v) => onChange("wiki.quality_auto_heal", v ? "true" : "false")}
          source={sourceBadge("wiki.quality_auto_heal", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.quality_judge_model", t)}
          type="text"
          value={values["wiki.quality_judge_model"] ?? ""}
          onChange={(v) => onChange("wiki.quality_judge_model", v)}
          source={sourceBadge("wiki.quality_judge_model", meta, t)}
        />
      </div>
    </SettingsCard>
  );
}
