import { Building2 } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function BusinessDomainSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  return (
    <SettingsCard
      title={t.configSettings.businessDomainTitle}
      icon={<Building2 size={18} className="text-sky-600" />}
    >
      <div className="space-y-3">
        <SettingsToggle
          label={configFieldLabel("wiki.business_domain_enabled", t)}
          checked={boolVal("wiki.business_domain_enabled")}
          onChange={(v) => onChange("wiki.business_domain_enabled", v ? "true" : "false")}
          source={sourceBadge("wiki.business_domain_enabled", meta, t)}
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <SettingsInput
            label={configFieldLabel("wiki.business_domain_sub_batch_size", t)}
            type="number"
            min={10}
            max={200}
            value={values["wiki.business_domain_sub_batch_size"] ?? ""}
            onChange={(v) => onChange("wiki.business_domain_sub_batch_size", v)}
            source={sourceBadge("wiki.business_domain_sub_batch_size", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.business_domain_classify_timeout", t)}
            type="number"
            min={60}
            max={3600}
            value={values["wiki.business_domain_classify_timeout"] ?? ""}
            onChange={(v) => onChange("wiki.business_domain_classify_timeout", v)}
            source={sourceBadge("wiki.business_domain_classify_timeout", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.business_domain_max_concurrency", t)}
            type="number"
            min={1}
            max={10}
            value={values["wiki.business_domain_max_concurrency"] ?? ""}
            onChange={(v) => onChange("wiki.business_domain_max_concurrency", v)}
            source={sourceBadge("wiki.business_domain_max_concurrency", meta, t)}
          />
          <SettingsInput
            label={configFieldLabel("wiki.business_domain_cache_ttl", t)}
            type="number"
            min={0}
            max={86400}
            value={values["wiki.business_domain_cache_ttl"] ?? ""}
            onChange={(v) => onChange("wiki.business_domain_cache_ttl", v)}
            source={sourceBadge("wiki.business_domain_cache_ttl", meta, t)}
          />
        </div>
      </div>
    </SettingsCard>
  );
}
