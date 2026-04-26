import { Server } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSelect from "../SettingsSelect";
import SettingsToggle from "../SettingsToggle";
import type { SectionProps } from "./types";

export default function SystemSection({ values, meta, onChange, t }: SectionProps) {
  const boolVal = (key: string) => values[key] === "true";

  const logOpts = ["DEBUG", "INFO", "WARNING", "ERROR"].map((lvl) => ({
    value: lvl,
    label: lvl,
  }));

  return (
    <SettingsCard title={t.configSettings.systemTitle} icon={<Server size={18} className="text-sky-600" />}>
      <SettingsInput
        label={configFieldLabel("host", t)}
        value={values.host ?? ""}
        onChange={(v) => onChange("host", v)}
        source={sourceBadge("host", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("port", t)}
        type="number"
        value={values.port ?? ""}
        onChange={(v) => onChange("port", v)}
        source={sourceBadge("port", meta, t)}
      />
      <SettingsSelect
        label={configFieldLabel("log_level", t)}
        value={(values.log_level || "INFO").toUpperCase()}
        onChange={(v) => onChange("log_level", v)}
        source={sourceBadge("log_level", meta, t)}
        options={logOpts}
      />
      <SettingsInput
        label={configFieldLabel("rate_limit_rpm", t)}
        type="number"
        value={values.rate_limit_rpm ?? ""}
        onChange={(v) => onChange("rate_limit_rpm", v)}
        source={sourceBadge("rate_limit_rpm", meta, t)}
      />
      <SettingsToggle
        label={configFieldLabel("require_auth", t)}
        checked={boolVal("require_auth")}
        onChange={(v) => onChange("require_auth", v ? "true" : "false")}
        source={sourceBadge("require_auth", meta, t)}
      />
    </SettingsCard>
  );
}
