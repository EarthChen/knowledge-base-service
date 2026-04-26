import { GitBranch } from "lucide-react";
import { configFieldLabel, configOptionLabel, humanizeKey, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSecretInput from "../SettingsSecretInput";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function WikiGitSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  const modeOpts = [
    { value: "incremental", label: configOptionLabel("incremental", t) },
    { value: "full", label: configOptionLabel("full", t) },
  ];
  const triggerOpts = [
    { value: "manual", label: configOptionLabel("manual", t) },
    { value: "schedule", label: humanizeKey("schedule") },
    { value: "webhook", label: humanizeKey("webhook") },
  ];

  return (
    <SettingsCard title={t.configSettings.wikiGitTitle} icon={<GitBranch size={18} className="text-sky-600" />}>
      <SettingsToggle
        label={configFieldLabel("wiki.git_publish_enabled", t)}
        checked={boolVal("wiki.git_publish_enabled")}
        onChange={(v) => onChange("wiki.git_publish_enabled", v ? "true" : "false")}
        source={sourceBadge("wiki.git_publish_enabled", meta, t)}
      />
      <SettingsSelect
        label={configFieldLabel("wiki.git_publish_mode", t)}
        value={values["wiki.git_publish_mode"] || "incremental"}
        onChange={(v) => onChange("wiki.git_publish_mode", v)}
        source={sourceBadge("wiki.git_publish_mode", meta, t)}
        options={modeOpts}
      />
      <SettingsSelect
        label={configFieldLabel("wiki.git_publish_trigger", t)}
        value={values["wiki.git_publish_trigger"] || "manual"}
        onChange={(v) => onChange("wiki.git_publish_trigger", v)}
        source={sourceBadge("wiki.git_publish_trigger", meta, t)}
        options={triggerOpts}
      />
      <SettingsInput
        label={configFieldLabel("wiki.git_remote_url", t)}
        value={values["wiki.git_remote_url"] ?? ""}
        onChange={(v) => onChange("wiki.git_remote_url", v)}
        source={sourceBadge("wiki.git_remote_url", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.git_branch", t)}
        value={values["wiki.git_branch"] ?? ""}
        onChange={(v) => onChange("wiki.git_branch", v)}
        source={sourceBadge("wiki.git_branch", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.git_author_name", t)}
        value={values["wiki.git_author_name"] ?? ""}
        onChange={(v) => onChange("wiki.git_author_name", v)}
        source={sourceBadge("wiki.git_author_name", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("wiki.git_author_email", t)}
        value={values["wiki.git_author_email"] ?? ""}
        onChange={(v) => onChange("wiki.git_author_email", v)}
        source={sourceBadge("wiki.git_author_email", meta, t)}
      />
      <SettingsSecretInput
        label={configFieldLabel("wiki.git_token", t)}
        value={values["wiki.git_token"] ?? ""}
        onChange={(v) => onChange("wiki.git_token", v)}
        source={sourceBadge("wiki.git_token", meta, t)}
      />
      <SettingsSelect
        label={configFieldLabel("wiki.export_default_view", t)}
        value={values["wiki.export_default_view"] || "business_domain"}
        onChange={(v) => onChange("wiki.export_default_view", v)}
        source={sourceBadge("wiki.export_default_view", meta, t)}
        options={[
          { value: "business_domain", label: configOptionLabel("business_domain", t) },
          { value: "code", label: configOptionLabel("code", t) },
        ]}
      />
      <SettingsSelect
        label={configFieldLabel("wiki.export_min_tier", t)}
        value={values["wiki.export_min_tier"] || "standard"}
        onChange={(v) => onChange("wiki.export_min_tier", v)}
        source={sourceBadge("wiki.export_min_tier", meta, t)}
        options={[
          { value: "standard", label: humanizeKey("standard") },
          { value: "core", label: humanizeKey("core") },
          { value: "skeleton", label: humanizeKey("skeleton") },
        ]}
      />
      <SettingsSelect
        label={configFieldLabel("wiki.export_dir_naming", t)}
        value={values["wiki.export_dir_naming"] || "original"}
        onChange={(v) => onChange("wiki.export_dir_naming", v)}
        source={sourceBadge("wiki.export_dir_naming", meta, t)}
        options={[
          { value: "original", label: configOptionLabel("original", t) },
          { value: "flat", label: humanizeKey("flat") },
        ]}
      />
    </SettingsCard>
  );
}
