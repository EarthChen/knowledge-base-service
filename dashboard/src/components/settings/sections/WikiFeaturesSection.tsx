import { BookOpen } from "lucide-react";
import { WIKI_FEATURES_KEYS } from "../systemConfigConstants";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function WikiFeaturesSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard title={t.configSettings.wikiFeaturesTitle} icon={<BookOpen size={18} className="text-sky-600" />}>
      {WIKI_FEATURES_KEYS.map((key) => (
        <SettingsToggle
          key={key}
          label={configFieldLabel(key, t)}
          checked={boolVal(key)}
          onChange={(v) => onChange(key, v ? "true" : "false")}
          source={sourceBadge(key, meta, t)}
        />
      ))}
    </SettingsCard>
  );
}
