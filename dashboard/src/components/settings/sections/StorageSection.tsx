import { Database, Loader2 } from "lucide-react";
import { configFieldLabel, sourceBadge } from "../configFieldLabels";
import SettingsCard from "../SettingsCard";
import SettingsInput from "../SettingsInput";
import SettingsSecretInput from "../SettingsSecretInput";
import type { ConnectionSectionProps } from "./types";

export default function StorageSection({
  values,
  meta,
  onChange,
  t,
  onTestConnection,
  testConnectionPending,
}: ConnectionSectionProps) {
  return (
    <SettingsCard title={t.configSettings.storageTitle} icon={<Database size={18} className="text-sky-600" />}>
      <SettingsInput
        label={configFieldLabel("falkordb.host", t)}
        value={values["falkordb.host"] ?? ""}
        onChange={(v) => onChange("falkordb.host", v)}
        source={sourceBadge("falkordb.host", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("falkordb.port", t)}
        type="number"
        value={values["falkordb.port"] ?? ""}
        onChange={(v) => onChange("falkordb.port", v)}
        source={sourceBadge("falkordb.port", meta, t)}
      />
      <SettingsSecretInput
        label={configFieldLabel("falkordb.password", t)}
        value={values["falkordb.password"] ?? ""}
        onChange={(v) => onChange("falkordb.password", v)}
        source={sourceBadge("falkordb.password", meta, t)}
      />
      <SettingsInput
        label={configFieldLabel("falkordb.graph_name", t)}
        value={values["falkordb.graph_name"] ?? ""}
        onChange={(v) => onChange("falkordb.graph_name", v)}
        source={sourceBadge("falkordb.graph_name", meta, t)}
      />
      <div>
        <button
          type="button"
          disabled={testConnectionPending}
          onClick={() => onTestConnection("falkordb")}
          className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
        >
          {testConnectionPending ? <Loader2 size={16} className="animate-spin" /> : null}
          {testConnectionPending ? t.configSettings.testing : t.configSettings.testConnection}
        </button>
      </div>
    </SettingsCard>
  );
}
