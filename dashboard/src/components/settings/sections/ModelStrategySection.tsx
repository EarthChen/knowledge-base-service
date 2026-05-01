import { Route } from "lucide-react";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import type { SectionProps } from "./types";

const STRATEGY_TASKS = [
  "classification",
  "generation",
  "reasoning",
  "evaluation",
  "heal",
  "diagram",
  "rag_plan",
  "rag_generate",
  "overview",
  "context",
] as const;

export default function ModelStrategySection({ values, meta, onChange, t }: SectionProps) {
  return (
    <SettingsCard
      title={t.configSettings.modelStrategy}
      icon={<Route size={18} className="text-amber-600" />}
    >
      <p className="mb-4 text-xs text-gray-500 dark:text-gray-400">
        {t.configSettings.modelStrategyDesc}
      </p>
      {STRATEGY_TASKS.map((task) => {
        const key = `llm.strategy.${task}`;
        return (
          <SettingsInput
            key={key}
            label={configFieldLabel(key, t) || task.replace(/_/g, " ")}
            value={values[key] ?? ""}
            onChange={(v) => onChange(key, v)}
            source={sourceBadge(key, meta, t)}
            placeholder='{"provider":"gateway","model":"gpt-4o"}'
          />
        );
      })}
    </SettingsCard>
  );
}
