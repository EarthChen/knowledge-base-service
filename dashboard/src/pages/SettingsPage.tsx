import { useEffect, useState } from "react";
import { Settings, CalendarClock } from "lucide-react";
import { useI18n } from "../i18n/context";
import { useAuth } from "../contexts/AuthContext";
import SystemConfigPanel from "../components/settings/SystemConfigPanel";
import GeneralSettingsPanel from "./panels/GeneralSettingsPanel";
import WebhookSettingsPanel from "./panels/WebhookSettingsPanel";
import SyncSettingsPanel from "./panels/SyncSettingsPanel";

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<"general" | "system">("general");
  const { t } = useI18n();
  const { isAdmin } = useAuth();

  useEffect(() => {
    if (!isAdmin && activeTab === "system") {
      setActiveTab("general");
    }
  }, [isAdmin, activeTab]);

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
        <Settings size={20} /> {t.settings.title}
      </h2>

      {isAdmin ? (
        <div
          className="flex gap-1 border-b border-gray-200 dark:border-gray-700"
          role="tablist"
          aria-label={t.settings.title}
        >
          <button
            type="button"
            role="tab"
            id="settings-tab-general"
            aria-selected={activeTab === "general"}
            aria-controls="settings-panel-general"
            onClick={() => setActiveTab("general")}
            className={`border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "general"
                ? "border-sky-600 text-sky-700 dark:border-sky-400 dark:text-sky-300"
                : "border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            {t.configSettings.tabGeneral}
          </button>
          <button
            type="button"
            role="tab"
            id="settings-tab-system"
            aria-selected={activeTab === "system"}
            aria-controls="settings-panel-system"
            onClick={() => setActiveTab("system")}
            className={`border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "system"
                ? "border-sky-600 text-sky-700 dark:border-sky-400 dark:text-sky-300"
                : "border-transparent text-gray-500 hover:text-gray-800 dark:text-gray-400 dark:hover:text-gray-200"
            }`}
          >
            {t.configSettings.tabSystemConfig}
          </button>
        </div>
      ) : null}

      {isAdmin && activeTab === "system" ? (
        <div
          role="tabpanel"
          id="settings-panel-system"
          aria-labelledby="settings-tab-system"
        >
          <SystemConfigPanel />
        </div>
      ) : null}

      {!isAdmin || activeTab === "general" ? (
        <div
          role={isAdmin ? "tabpanel" : undefined}
          id={isAdmin ? "settings-panel-general" : undefined}
          aria-labelledby={isAdmin ? "settings-tab-general" : undefined}
        >
          <div className="space-y-6">
            <GeneralSettingsPanel />
            <WebhookSettingsPanel />
            <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
              <div className="flex items-center gap-2">
                <CalendarClock size={18} className="text-gray-500 dark:text-gray-400" />
                <h3 className="text-sm font-medium text-gray-800 dark:text-gray-100">
                  {t.settings.scheduledRegenTitle}
                </h3>
              </div>
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                {t.settings.scheduledRegenDesc}
              </p>
              <div className="mt-4 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-sm text-gray-700 dark:border-gray-700 dark:bg-gray-800/80 dark:text-gray-300">
                {t.settings.scheduledRegenStatus}
              </div>
              <p className="mt-3 text-xs text-amber-800 dark:text-amber-200">
                {t.settings.scheduledRegenTip}
              </p>
            </div>
            <SyncSettingsPanel />
          </div>
        </div>
      ) : null}
    </div>
  );
}
