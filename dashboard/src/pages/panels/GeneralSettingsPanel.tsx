import { useState } from "react";
import { Save, Eye, EyeOff, Globe, BookOpen } from "lucide-react";
import { getToken, setToken } from "../../api/client";
import { useHealth } from "../../api/hooks";
import { useI18n } from "../../i18n/context";
import { useToast } from "../../components/Toast";
import type { Locale } from "../../i18n/types";
import { SETTINGS_INPUT_CLASS } from "./settingsInputClass";

const LOCALE_OPTIONS: { value: Locale }[] = [{ value: "en" }, { value: "zh" }];

export default function GeneralSettingsPanel() {
  const [tokenValue, setTokenValue] = useState(getToken());
  const [showToken, setShowToken] = useState(false);
  const { data: health, refetch } = useHealth();
  const { t, locale, setLocale } = useI18n();
  const { toast } = useToast();

  function handleSave() {
    setToken(tokenValue.trim());
    toast("success", t.settings.tokenSaved);
    refetch();
  }

  return (
    <div>
      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-gray-500 dark:text-gray-400" />
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">{t.settings.language}</h3>
        </div>
        <div className="mt-3 flex gap-2">
          {LOCALE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setLocale(opt.value)}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                locale === opt.value
                  ? "bg-sky-100 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400"
                  : "border border-gray-300 text-gray-500 hover:text-gray-700 dark:border-gray-600 dark:text-gray-400 dark:hover:text-gray-200"
              }`}
            >
              {opt.value === "en" ? t.settings.localeEnglish : t.settings.localeChinese}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">{t.settings.apiToken}</h3>
        <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
          {t.settings.apiTokenDesc}
        </p>
        <div className="mt-3 flex gap-2">
          <div className="relative flex-1">
            <input
              type={showToken ? "text" : "password"}
              value={tokenValue}
              onChange={(e) => setTokenValue(e.target.value)}
              placeholder={t.settings.tokenPlaceholder}
              className={SETTINGS_INPUT_CLASS}
            />
            <button
              type="button"
              onClick={() => setShowToken(!showToken)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
            >
              {showToken ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
          <button
            onClick={handleSave}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-sky-500"
          >
            <Save size={14} /> {t.settings.save}
          </button>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">{t.settings.serviceInfo}</h3>
        <div className="mt-3 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-400 dark:text-gray-500">{t.settings.health}</span>
            <span className={health?.status === "ok" ? "text-emerald-600 dark:text-emerald-400" : "text-amber-600 dark:text-amber-400"}>
              {health?.status === "ok" ? t.sidebar.healthy : t.sidebar.unreachable}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400 dark:text-gray-500">{t.settings.apiBase}</span>
            <span className="font-mono text-xs text-gray-700 dark:text-gray-300">/api/v1</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400 dark:text-gray-500">{t.settings.deployment}</span>
            <span className="text-gray-700 dark:text-gray-300">{t.settings.deploymentValue}</span>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-gray-500 dark:text-gray-400" />
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {t.settings.wikiReadonlyTitle}
          </h3>
        </div>
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          {t.settings.wikiReadonlyDesc}
        </p>
        <div className="mt-4 space-y-4 text-sm">
          {!health?.wiki ? (
            <p className="text-gray-500 dark:text-gray-400">
              {t.settings.wikiNoWikiInHealth}
            </p>
          ) : (
            <>
              <label className="flex cursor-not-allowed items-center justify-between gap-3 rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2 opacity-90 dark:border-gray-700 dark:bg-gray-800/60">
                <span className="text-gray-600 dark:text-gray-300">{t.settings.cotEnabled}</span>
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-gray-300 text-sky-600 dark:border-gray-600"
                  checked={health.wiki.cot_enabled}
                  readOnly
                  disabled
                  aria-readonly
                />
              </label>
              <div className="space-y-1">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  {t.settings.cotAnalysisModel}
                </div>
                <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 font-mono text-xs text-gray-800 dark:border-gray-700 dark:bg-gray-800/80 dark:text-gray-200">
                  {health.wiki.cot_analysis_model?.trim()
                    ? health.wiki.cot_analysis_model
                    : t.settings.valueNotSet}
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400">
                  {t.settings.cotGenerationModel}
                </div>
                <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 font-mono text-xs text-gray-800 dark:border-gray-700 dark:bg-gray-800/80 dark:text-gray-200">
                  {health.wiki.cot_generation_model?.trim()
                    ? health.wiki.cot_generation_model
                    : t.settings.valueNotSet}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
