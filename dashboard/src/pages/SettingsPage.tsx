import { useState } from "react";
import { Settings, Save, Eye, EyeOff, Globe } from "lucide-react";
import { getToken, setToken } from "../api/client";
import { useHealth } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useToast } from "../components/Toast";
import type { Locale } from "../i18n/types";

const LOCALE_OPTIONS: { value: Locale; label: string }[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "简体中文" },
];

export default function SettingsPage() {
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

  const inputClass =
    "w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder-slate-500 outline-none focus:border-sky-500/50 focus:ring-1 focus:ring-sky-500/30";

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
        <Settings size={20} /> {t.settings.title}
      </h2>

      <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-slate-400" />
          <h3 className="text-sm font-medium text-slate-300">{t.settings.language}</h3>
        </div>
        <div className="mt-3 flex gap-2">
          {LOCALE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setLocale(opt.value)}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                locale === opt.value
                  ? "bg-sky-500/20 text-sky-400"
                  : "border border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
        <h3 className="text-sm font-medium text-slate-300">{t.settings.apiToken}</h3>
        <p className="mt-1 text-xs text-slate-500">
          {t.settings.apiTokenDesc}
        </p>
        <div className="mt-3 flex gap-2">
          <div className="relative flex-1">
            <input
              type={showToken ? "text" : "password"}
              value={tokenValue}
              onChange={(e) => setTokenValue(e.target.value)}
              placeholder={t.settings.tokenPlaceholder}
              className={inputClass}
            />
            <button
              type="button"
              onClick={() => setShowToken(!showToken)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
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

      <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
        <h3 className="text-sm font-medium text-slate-300">{t.settings.serviceInfo}</h3>
        <div className="mt-3 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-slate-500">{t.settings.health}</span>
            <span className={health?.status === "ok" ? "text-emerald-400" : "text-amber-400"}>
              {health?.status === "ok" ? t.sidebar.healthy : t.sidebar.unreachable}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500">{t.settings.apiBase}</span>
            <span className="font-mono text-xs text-slate-300">/api/v1</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-500">{t.settings.deployment}</span>
            <span className="text-slate-300">{t.settings.deploymentValue}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
