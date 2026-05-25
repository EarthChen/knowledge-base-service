import { Users } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

const GROUPING_OPTIONS = [
  { value: "flat", label: "Flat" },
  { value: "hierarchical", label: "Hierarchical" },
];

export default function DelegationEnrichmentSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard
      title={t.configSettings.delegationEnrichmentTitle}
      icon={<Users size={18} className="text-sky-600" />}
    >
      <div className="space-y-3">
        <SettingsToggle
          label={configFieldLabel("wiki.delegation_enabled", t)}
          checked={boolVal("wiki.delegation_enabled")}
          onChange={(v) => onChange("wiki.delegation_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.delegation_enabled", meta, t)}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SettingsInput
            label={configFieldLabel("wiki.delegation_max_children", t)}
            type="number"
            min={5}
            max={100}
            value={values["wiki.delegation_max_children"] ?? ""}
            onChange={(v) => onChange("wiki.delegation_max_children", v)}
            source={sourceBadge("wiki.delegation_max_children", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.delegation_max_code_lines", t)}
            type="number"
            min={100}
            max={50000}
            value={values["wiki.delegation_max_code_lines"] ?? ""}
            onChange={(v) => onChange("wiki.delegation_max_code_lines", v)}
            source={sourceBadge("wiki.delegation_max_code_lines", meta, t)}
          />
        </div>
        <SettingsSelect
          label={configFieldLabel("wiki.delegation_grouping_strategy", t)}
          value={values["wiki.delegation_grouping_strategy"] ?? ""}
          onChange={(v) => onChange("wiki.delegation_grouping_strategy", v)}
          options={GROUPING_OPTIONS}
          source={sourceBadge("wiki.delegation_grouping_strategy", meta, t)}
        />
        <div className="border-t border-gray-200 pt-3 dark:border-gray-700">
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
        </div>
      </div>
    </SettingsCard>
  );
}
