import { BookOpen } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

const WIKI_FEATURE_GROUPS: { titleKey: keyof SectionProps["t"]["configSettings"]; keys: readonly string[] }[] = [
  {
    titleKey: "wikiGroupCore",
    keys: [
      "wiki.tree_enabled",
      "wiki.dual_view_enabled",
      "wiki.cross_reference_enabled",
      "wiki.coverage_report_enabled",
      "wiki.stale_detection_enabled",
      "wiki.suggested_questions_enabled",
      "wiki.knowledge_injection_enabled",
      "wiki.cross_repo_domain_enabled",
      "wiki.auto_update_on_index",
    ],
  },
  {
    titleKey: "wikiGroupKnowledgeQuality",
    keys: [
      "wiki.confidence_scoring_enabled",
      "wiki.contradiction_detection_enabled",
      "wiki.supersession_tracking_enabled",
    ],
  },
  {
    titleKey: "wikiGroupMemoryEvolution",
    keys: ["wiki.memory_tiers_enabled", "wiki.forgetting_enabled", "wiki.schema_validation_enabled"],
  },
  {
    titleKey: "wikiGroupAutomation",
    keys: [
      "wiki.mcp_server_enabled",
      "wiki.feedback_enabled",
      "wiki.lint_scheduler_enabled",
      "wiki.auto_heal_enabled",
      "wiki.deep_research_enabled",
      "wiki.concept_merging_enabled",
      "wiki.business_domain_enabled",
    ],
  },
];

export default function WikiFeaturesSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard title={t.configSettings.wikiFeaturesTitle} icon={<BookOpen size={18} className="text-sky-600" />}>
      <div className="space-y-6">
      {WIKI_FEATURE_GROUPS.map((group) => (
        <div key={group.titleKey} className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t.configSettings[group.titleKey] as string}
          </p>
          {group.keys.map((key) => (
            <SettingsToggle
              key={key}
              label={configFieldLabel(key, t)}
              checked={boolVal(key)}
              onChange={(v) => onChange(key, v ? "true" : "false")}
              source={sourceBadge(key, meta, t)}
            />
          ))}
        </div>
      ))}
      </div>
    </SettingsCard>
  );
}
