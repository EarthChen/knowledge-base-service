import { Layout } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "zh", label: "中文" },
  { value: "auto", label: "Auto-detect" },
];

export default function CompositionSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard
      title={t.configSettings.compositionTitle}
      icon={<Layout size={18} className="text-sky-600" />}
    >
      <div className="space-y-3">
        <SettingsSelect
          label={configFieldLabel("wiki.wiki_content_language", t)}
          value={values["wiki.wiki_content_language"] ?? ""}
          onChange={(v) => onChange("wiki.wiki_content_language", v)}
          options={LANGUAGE_OPTIONS}
          source={sourceBadge("wiki.wiki_content_language", meta, t)}
        />
        <SettingsToggle
          label={configFieldLabel("wiki.flow_compose_enabled", t)}
          checked={boolVal("wiki.flow_compose_enabled")}
          onChange={(v) => onChange("wiki.flow_compose_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.flow_compose_enabled", meta, t)}
        />
        <SettingsToggle
          label={configFieldLabel("wiki.guided_tour_enabled", t)}
          checked={boolVal("wiki.guided_tour_enabled")}
          onChange={(v) => onChange("wiki.guided_tour_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.guided_tour_enabled", meta, t)}
        />
        <SettingsToggle
          label={configFieldLabel("wiki.business_wiki_skip_repo_pages", t)}
          checked={boolVal("wiki.business_wiki_skip_repo_pages")}
          onChange={(v) => onChange("wiki.business_wiki_skip_repo_pages", v ? "true" : "false")}
          source={sourceBadge("wiki.business_wiki_skip_repo_pages", meta, t)}
        />
      </div>
    </SettingsCard>
  );
}
