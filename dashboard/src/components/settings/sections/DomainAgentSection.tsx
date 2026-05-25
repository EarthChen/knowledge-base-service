import { Bot } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import type { SectionProps } from "./types";

export default function DomainAgentSection({ values, meta, onChange, t }: SectionProps) {
  return (
    <SettingsCard
      title={t.configSettings.domainAgentTitle}
      icon={<Bot size={18} className="text-sky-600" />}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_max_iterations_core", t)}
          type="number"
          min={1}
          max={100}
          value={values["wiki.domain_agent_max_iterations_core"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_max_iterations_core", v)}
          source={sourceBadge("wiki.domain_agent_max_iterations_core", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_max_iterations_standard", t)}
          type="number"
          min={1}
          max={50}
          value={values["wiki.domain_agent_max_iterations_standard"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_max_iterations_standard", v)}
          source={sourceBadge("wiki.domain_agent_max_iterations_standard", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_max_iterations_skeleton", t)}
          type="number"
          min={1}
          max={20}
          value={values["wiki.domain_agent_max_iterations_skeleton"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_max_iterations_skeleton", v)}
          source={sourceBadge("wiki.domain_agent_max_iterations_skeleton", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_timeout_sec", t)}
          type="number"
          min={60}
          max={3600}
          value={values["wiki.domain_agent_timeout_sec"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_timeout_sec", v)}
          source={sourceBadge("wiki.domain_agent_timeout_sec", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_explore_max_rounds", t)}
          type="number"
          min={1}
          max={20}
          value={values["wiki.domain_agent_explore_max_rounds"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_explore_max_rounds", v)}
          source={sourceBadge("wiki.domain_agent_explore_max_rounds", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_explore_max_tool_calls", t)}
          type="number"
          min={5}
          max={100}
          value={values["wiki.domain_agent_explore_max_tool_calls"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_explore_max_tool_calls", v)}
          source={sourceBadge("wiki.domain_agent_explore_max_tool_calls", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_early_exit_quality", t)}
          type="number"
          min={0}
          max={1}
          value={values["wiki.domain_agent_early_exit_quality"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_early_exit_quality", v)}
          source={sourceBadge("wiki.domain_agent_early_exit_quality", meta, t)}
        />
        <SettingsInput
          label={configFieldLabel("wiki.domain_agent_early_exit_min_chars", t)}
          type="number"
          min={0}
          max={5000}
          value={values["wiki.domain_agent_early_exit_min_chars"] ?? ""}
          onChange={(v) => onChange("wiki.domain_agent_early_exit_min_chars", v)}
          source={sourceBadge("wiki.domain_agent_early_exit_min_chars", meta, t)}
        />
      </div>
    </SettingsCard>
  );
}
