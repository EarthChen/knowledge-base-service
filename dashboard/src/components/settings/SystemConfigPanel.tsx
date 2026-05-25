import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { useAllSettings } from "../../hooks/useSettings";
import { useTestConnection, useUpdateSettings } from "../../hooks/useUpdateSettings";
import { getSettingCategory } from "../../hooks/settingsCategory";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import { useToast } from "../Toast";
import { SkeletonLine } from "../Skeleton";
import EmbeddingSection from "./sections/EmbeddingSection";
import LLMSection from "./sections/LLMSection";
import LLMProviderPoolSection from "./sections/LLMProviderPoolSection";
import ModelStrategySection from "./sections/ModelStrategySection";
import StorageSection from "./sections/StorageSection";
import SystemSection from "./sections/SystemSection";
import WikiFeaturesSection from "./sections/WikiFeaturesSection";
import WikiGenerationSection from "./sections/WikiGenerationSection";
import PipelineConcurrencySection from "./sections/PipelineConcurrencySection";
import DomainAgentSection from "./sections/DomainAgentSection";
import CompositionSection from "./sections/CompositionSection";
import DomainReassemblySection from "./sections/DomainReassemblySection";
import HealingQualitySection from "./sections/HealingQualitySection";
import DelegationEnrichmentSection from "./sections/DelegationEnrichmentSection";
import BusinessDomainSection from "./sections/BusinessDomainSection";
import IncrementalBudgetSection from "./sections/IncrementalBudgetSection";
import WikiGitSection from "./sections/WikiGitSection";
import { configFieldLabel } from "./configFieldLabels";
import {
  flattenCategories,
  mergeKeys,
  validateNumberFieldValue,
  type SettingMeta,
} from "./systemConfigConstants";

export default function SystemConfigPanel() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { data, isLoading, error, refetch, dataUpdatedAt } = useAllSettings();
  const updateSettings = useUpdateSettings();
  const testConnection = useTestConnection();

  const [values, setValues] = useState<Record<string, string>>({});
  const [baseline, setBaseline] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState<Record<string, SettingMeta>>({});
  const [syncedAt, setSyncedAt] = useState(0);

  const dirtyKeys = useMemo(
    () => Object.keys(values).filter((k) => values[k] !== baseline[k]),
    [values, baseline],
  );
  const dirtyCount = dirtyKeys.length;

  useEffect(() => {
    if (!data?.categories || dataUpdatedAt === syncedAt) return;
    if (dirtyCount > 0) return;
    const flat = flattenCategories(data.categories);
    setValues(mergeKeys(flat.values));
    setBaseline(mergeKeys(flat.values));
    setMeta(flat.meta);
    setSyncedAt(dataUpdatedAt);
  }, [data, dataUpdatedAt, syncedAt, dirtyCount]);

  const setVal = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  async function handleSave() {
    if (dirtyCount === 0) return;
    for (const key of dirtyKeys) {
      const validationError = validateNumberFieldValue(key, values[key] ?? "");
      if (validationError) {
        const label = configFieldLabel(key, t);
        if (validationError.kind === "empty") {
          toast("error", t.configSettings.validationNumberEmpty.replace("{field}", label));
        } else {
          toast(
            "error",
            t.configSettings.validationNumberOutOfRange
              .replace("{field}", label)
              .replace("{min}", String(validationError.min))
              .replace("{max}", String(validationError.max)),
          );
        }
        return;
      }
    }
    const updates = dirtyKeys.map((key) => ({
      key,
      value: values[key],
      category: meta[key]?.category ?? getSettingCategory(key),
    }));
    try {
      await updateSettings.mutateAsync({ settings: updates });
      const res = await refetch();
      if (res.data?.categories) {
        const flat = flattenCategories(res.data.categories);
        setMeta(flat.meta);
        setValues(mergeKeys(flat.values));
        setBaseline(mergeKeys(flat.values));
      }
      toast("success", t.configSettings.saved);
    } catch (e) {
      toast("error", getErrorMessage(e, t.common.unexpectedError) || t.configSettings.saveFailed);
    }
  }

  async function runTest(target: string) {
    try {
      const r = await testConnection.mutateAsync(target);
      if (r.status === "ok") {
        toast("success", `${t.configSettings.connectionOk}: ${r.message}`);
      } else {
        toast("error", `${t.configSettings.connectionFailed}: ${r.message}`);
      }
    } catch (e) {
      toast("error", getErrorMessage(e, t.common.unexpectedError) || t.configSettings.connectionFailed);
    }
  }

  if (isLoading && !data) {
    return (
      <div className="space-y-4">
        <SkeletonLine className="h-10 w-full max-w-md" />
        <SkeletonLine className="h-40 w-full" />
        <SkeletonLine className="h-40 w-full" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
        {getErrorMessage(error, t.common.unexpectedError)}
      </div>
    );
  }

  const sectionProps = { values, meta, onChange: setVal, t };

  return (
    <div className="relative space-y-6 pb-24">
      <WikiFeaturesSection {...sectionProps} />
      <WikiGenerationSection {...sectionProps} />
      <PipelineConcurrencySection {...sectionProps} />
      <DomainAgentSection {...sectionProps} />
      <CompositionSection {...sectionProps} />
      <DomainReassemblySection {...sectionProps} />
      <HealingQualitySection {...sectionProps} />
      <DelegationEnrichmentSection {...sectionProps} />
      <BusinessDomainSection {...sectionProps} />
      <IncrementalBudgetSection {...sectionProps} />
      <WikiGitSection {...sectionProps} />
      <LLMSection
        {...sectionProps}
        onTestConnection={runTest}
        testConnectionPending={testConnection.isPending}
      />
      <LLMProviderPoolSection {...sectionProps} />
      <ModelStrategySection {...sectionProps} />
      <StorageSection
        {...sectionProps}
        onTestConnection={runTest}
        testConnectionPending={testConnection.isPending}
      />
      <EmbeddingSection {...sectionProps} />
      <SystemSection {...sectionProps} />

      {dirtyCount > 0 && (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 flex-col items-center gap-2 sm:flex-row">
          <span className="rounded-full bg-gray-900/90 px-3 py-1 text-xs text-white shadow-lg dark:bg-gray-100 dark:text-gray-900">
            {t.configSettings.unsavedChanges.replace("{count}", String(dirtyCount))}
          </span>
          <button
            type="button"
            disabled={updateSettings.isPending}
            onClick={handleSave}
            className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-sky-500 disabled:opacity-50"
          >
            {updateSettings.isPending ? <Loader2 size={16} className="animate-spin" /> : null}
            {updateSettings.isPending ? t.configSettings.saving : `${t.configSettings.saveChanges} (${dirtyCount})`}
          </button>
        </div>
      )}
    </div>
  );
}
