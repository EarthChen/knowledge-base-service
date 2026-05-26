import { Workflow } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import type { SectionProps } from "./types";

type NumberField = { key: string; min: number; max: number };

const CONCURRENCY_FIELDS: NumberField[] = [
  { key: "wiki.compose_concurrency", min: 1, max: 50 },
  { key: "wiki.heal_concurrency", min: 1, max: 20 },
  { key: "wiki.domain_agent_concurrency", min: 1, max: 10 },
  { key: "wiki.module_compose_concurrency", min: 1, max: 10 },
  { key: "wiki.flow_compose_concurrency", min: 1, max: 10 },
];

const HEAL_ROUND_FIELDS: NumberField[] = [
  { key: "wiki.heal_max_rounds_core", min: 0, max: 5 },
  { key: "wiki.heal_max_rounds_standard", min: 0, max: 5 },
];

const RATE_LIMIT_FIELDS: NumberField[] = [{ key: "wiki.llm_global_rpm_limit", min: 0, max: 300 }];

const DOMAIN_SPLIT_FIELDS: NumberField[] = [
  { key: "wiki.domain_split_threshold", min: 5, max: 50 },
  { key: "wiki.domain_split_max_depth", min: 1, max: 5 },
];

function NumberFieldGroup({
  fields,
  values,
  meta,
  onChange,
  t,
}: SectionProps & { fields: NumberField[] }) {
  return (
    <>
      {fields.map(({ key, min, max }) => (
        <SettingsInput
          key={key}
          label={configFieldLabel(key, t)}
          type="number"
          min={min}
          max={max}
          value={values[key] ?? ""}
          onChange={(v) => onChange(key, v)}
          source={sourceBadge(key, meta, t)}
        />
      ))}
    </>
  );
}

export default function PipelineConcurrencySection({ values, meta, onChange, t }: SectionProps) {
  return (
    <SettingsCard
      title={t.configSettings.pipelineConcurrencyTitle}
      icon={<Workflow size={18} className="text-sky-600" />}
    >
      <div className="space-y-6">
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t.configSettings.pipelineGroupConcurrency}
          </p>
          <NumberFieldGroup fields={CONCURRENCY_FIELDS} values={values} meta={meta} onChange={onChange} t={t} />
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t.configSettings.pipelineGroupHealRounds}
          </p>
          <NumberFieldGroup fields={HEAL_ROUND_FIELDS} values={values} meta={meta} onChange={onChange} t={t} />
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t.configSettings.pipelineGroupRateLimit}
          </p>
          <NumberFieldGroup fields={RATE_LIMIT_FIELDS} values={values} meta={meta} onChange={onChange} t={t} />
        </div>
        <div className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {t.configSettings.pipelineGroupDomainSplit}
          </p>
          <NumberFieldGroup fields={DOMAIN_SPLIT_FIELDS} values={values} meta={meta} onChange={onChange} t={t} />
        </div>
      </div>
    </SettingsCard>
  );
}
