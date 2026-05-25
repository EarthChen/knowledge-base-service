import { GitMerge } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function DomainReassemblySection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard
      title={t.configSettings.domainReassemblyTitle}
      icon={<GitMerge size={18} className="text-sky-600" />}
    >
      <div className="space-y-3">
        <SettingsToggle
          label={configFieldLabel("wiki.domain_reassembly_enabled", t)}
          checked={boolVal("wiki.domain_reassembly_enabled")}
          onChange={(v) => onChange("wiki.domain_reassembly_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.domain_reassembly_enabled", meta, t)}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SettingsInput
            label={configFieldLabel("wiki.reassembly_merge_threshold", t)}
            type="number"
            min={0.5}
            max={1}
            value={values["wiki.reassembly_merge_threshold"] ?? ""}
            onChange={(v) => onChange("wiki.reassembly_merge_threshold", v)}
            source={sourceBadge("wiki.reassembly_merge_threshold", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.embedding_merge_threshold", t)}
            type="number"
            min={0.5}
            max={1}
            value={values["wiki.embedding_merge_threshold"] ?? ""}
            onChange={(v) => onChange("wiki.embedding_merge_threshold", v)}
            source={sourceBadge("wiki.embedding_merge_threshold", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.reassembly_orphan_threshold", t)}
            type="number"
            min={0.3}
            max={1}
            value={values["wiki.reassembly_orphan_threshold"] ?? ""}
            onChange={(v) => onChange("wiki.reassembly_orphan_threshold", v)}
            source={sourceBadge("wiki.reassembly_orphan_threshold", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.reassembly_max_moves_pct", t)}
            type="number"
            min={0}
            max={1}
            value={values["wiki.reassembly_max_moves_pct"] ?? ""}
            onChange={(v) => onChange("wiki.reassembly_max_moves_pct", v)}
            source={sourceBadge("wiki.reassembly_max_moves_pct", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.consolidation_min_count", t)}
            type="number"
            min={2}
            max={20}
            value={values["wiki.consolidation_min_count"] ?? ""}
            onChange={(v) => onChange("wiki.consolidation_min_count", v)}
            source={sourceBadge("wiki.consolidation_min_count", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.consolidation_min_domains", t)}
            type="number"
            min={2}
            max={20}
            value={values["wiki.consolidation_min_domains"] ?? ""}
            onChange={(v) => onChange("wiki.consolidation_min_domains", v)}
            source={sourceBadge("wiki.consolidation_min_domains", meta, t)}
          />
        </div>
        <SettingsToggle
          label={configFieldLabel("wiki.reassembly_respect_user_modified", t)}
          checked={boolVal("wiki.reassembly_respect_user_modified")}
          onChange={(v) => onChange("wiki.reassembly_respect_user_modified", v ? "true" : "false")}
          source={sourceBadge("wiki.reassembly_respect_user_modified", meta, t)}
        />
      </div>
    </SettingsCard>
  );
}
