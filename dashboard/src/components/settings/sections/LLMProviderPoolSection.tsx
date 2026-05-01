import { Server } from "lucide-react";
import SettingsCard from "../SettingsCard";
import type { SectionProps } from "./types";

export default function LLMProviderPoolSection({ values, meta: _meta, onChange, t }: SectionProps) {
  const raw = values["llm.providers"] ?? "{}";

  return (
    <SettingsCard
      title={t.configSettings.llmProviderPool}
      icon={<Server size={18} className="text-violet-600" />}
    >
      <div className="space-y-2">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
          {t.configSettings.llmProviderPoolDesc}
        </label>
        <textarea
          className="w-full rounded-lg border border-gray-300 bg-white p-3 font-mono text-sm text-gray-900 focus:border-violet-500 focus:ring-1 focus:ring-violet-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
          rows={10}
          value={raw}
          onChange={(e) => onChange("llm.providers", e.target.value)}
          placeholder='{"openai": {"api_key": "sk-...", "base_url": "https://api.openai.com/v1", "models": ["gpt-4o", "gpt-4o-mini"]}}'
        />
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t.configSettings.llmProviderPoolHint}
        </p>
      </div>
    </SettingsCard>
  );
}
