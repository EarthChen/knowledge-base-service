import { useEffect, useState } from "react";
import FocusTrap from "../components/FocusTrap";
import {
  Settings,
  Save,
  Eye,
  EyeOff,
  Globe,
  Clock,
  Plus,
  Pencil,
  Trash2,
  RefreshCw,
  Loader2,
  Webhook,
  CalendarClock,
  BookOpen,
} from "lucide-react";
import { getToken, setToken } from "../api/client";
import {
  useHealth,
  useRepositories,
  useSyncSchedules,
  useCreateSyncSchedule,
  useDeleteSyncSchedule,
  useTriggerSync,
  useWebhookConfig,
  useUpdateWebhookConfig,
} from "../api/hooks";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { useToast } from "../components/Toast";
import type { Locale } from "../i18n/types";
import type { SyncSchedule, SyncScheduleRequest, WebhookConfig } from "../api/types";
import { useAuth } from "../contexts/AuthContext";
import { SkeletonLine } from "../components/Skeleton";
import SystemConfigPanel from "../components/settings/SystemConfigPanel";

const LOCALE_OPTIONS: { value: Locale }[] = [{ value: "en" }, { value: "zh" }];

function schedulePath(repo: string) {
  return repo.split("/").map(encodeURIComponent).join("/");
}

const WEBHOOK_PROVIDERS = ["github", "gitlab", "gitea"] as const;

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState<"general" | "system">("general");
  const [tokenValue, setTokenValue] = useState(getToken());
  const [showToken, setShowToken] = useState(false);
  const { data: health, refetch } = useHealth();
  const { t, locale, setLocale } = useI18n();
  const { toast } = useToast();
  const { isAdmin, isLoading: authLoading } = useAuth();

  useEffect(() => {
    if (!isAdmin && activeTab === "system") {
      setActiveTab("general");
    }
  }, [isAdmin, activeTab]);

  const {
    data: webhookConfig,
    isLoading: webhookLoading,
    error: webhookError,
    refetch: refetchWebhook,
  } = useWebhookConfig({ enabled: isAdmin && !authLoading });
  const updateWebhook = useUpdateWebhookConfig();

  const { data: reposData } = useRepositories();
  const {
    data: schedulesData,
    isLoading: schedulesLoading,
    error: schedulesError,
    refetch: refetchSchedules,
  } = useSyncSchedules({ enabled: isAdmin && !authLoading });

  const upsert = useCreateSyncSchedule();
  const del = useDeleteSyncSchedule();
  const trigger = useTriggerSync();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<SyncSchedule | null>(null);
  const [formRepo, setFormRepo] = useState("");
  const [formGitUrl, setFormGitUrl] = useState("");
  const [formBranch, setFormBranch] = useState("");
  const [formInterval, setFormInterval] = useState(60);
  const [formEnabled, setFormEnabled] = useState(true);

  const [webhookModalOpen, setWebhookModalOpen] = useState(false);
  const [whEnabled, setWhEnabled] = useState(false);
  const [whDebounce, setWhDebounce] = useState(60);
  const [whBranches, setWhBranches] = useState("");
  const [whSecretGithub, setWhSecretGithub] = useState("");
  const [whSecretGitlab, setWhSecretGitlab] = useState("");
  const [whSecretGitea, setWhSecretGitea] = useState("");

  function openWebhookModal() {
    const c = webhookConfig;
    const unmask = (val: string | undefined) =>
      val === "***configured***" ? "" : (val ?? "");
    if (c) {
      setWhEnabled(c.enabled);
      setWhDebounce(c.debounce_seconds);
      setWhBranches(c.auto_update_branches.join(", "));
      setWhSecretGithub(unmask(c.providers?.github?.secret));
      setWhSecretGitlab(unmask(c.providers?.gitlab?.secret));
      setWhSecretGitea(unmask(c.providers?.gitea?.secret));
    } else {
      setWhEnabled(false);
      setWhDebounce(60);
      setWhBranches("");
      setWhSecretGithub("");
      setWhSecretGitlab("");
      setWhSecretGitea("");
    }
    setWebhookModalOpen(true);
  }

  function closeWebhookModal() {
    setWebhookModalOpen(false);
  }

  async function submitWebhookModal(e: React.FormEvent) {
    e.preventDefault();
    const debounce = Math.min(86400, Math.max(1, Math.floor(Number(whDebounce))));
    const branches = whBranches
      .split(/[,，]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const base = webhookConfig;
    const resolveSecret = (field: string, provider: string) => {
      if (field.trim()) return field.trim();
      const existing = base?.providers?.[provider]?.secret ?? "";
      return existing === "***configured***" ? "" : existing;
    };
    const body: WebhookConfig = {
      enabled: whEnabled,
      debounce_seconds: debounce,
      auto_update_branches: branches,
      providers: {
        ...(base?.providers ?? {}),
        github: { secret: resolveSecret(whSecretGithub, "github") },
        gitlab: { secret: resolveSecret(whSecretGitlab, "gitlab") },
        gitea: { secret: resolveSecret(whSecretGitea, "gitea") },
      },
    };
    try {
      await updateWebhook.mutateAsync(body);
      toast("success", t.webhook.configSaved);
      closeWebhookModal();
      refetchWebhook();
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError));
    }
  }

  function handleSave() {
    setToken(tokenValue.trim());
    toast("success", t.settings.tokenSaved);
    refetch();
  }

  function openAdd() {
    setEditing(null);
    setFormRepo("");
    setFormGitUrl("");
    setFormBranch("");
    setFormInterval(60);
    setFormEnabled(true);
    setModalOpen(true);
  }

  function openEdit(row: SyncSchedule) {
    setEditing(row);
    setFormRepo(row.repo_name);
    setFormGitUrl(row.git_url);
    setFormBranch(row.branch ?? "");
    setFormInterval(row.interval_minutes);
    setFormEnabled(row.enabled);
    setModalOpen(true);
  }

  function closeModal() {
    setModalOpen(false);
  }

  async function submitModal(e: React.FormEvent) {
    e.preventDefault();
    const rn = formRepo.trim();
    const gu = formGitUrl.trim();
    if (!rn) {
      toast("error", t.sync.repoRequired);
      return;
    }
    if (!gu) {
      toast("error", t.sync.gitUrlRequired);
      return;
    }
    const br = formBranch.trim();
    const body: SyncScheduleRequest = {
      repo_name: rn,
      git_url: gu,
      branch: br ? br : null,
      interval_minutes: Math.min(1440, Math.max(5, formInterval)),
      enabled: formEnabled,
    };
    try {
      await upsert.mutateAsync(body);
      toast("success", t.sync.saveSuccess);
      closeModal();
      refetchSchedules();
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError));
    }
  }

  async function handleToggleEnabled(row: SyncSchedule, enabled: boolean) {
    const body: SyncScheduleRequest = {
      repo_name: row.repo_name,
      git_url: row.git_url,
      branch: row.branch,
      interval_minutes: row.interval_minutes,
      enabled,
    };
    try {
      await upsert.mutateAsync(body);
      toast("success", t.sync.saveSuccess);
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError));
    }
  }

  async function handleDelete(repo: string) {
    const msg = t.sync.deleteConfirm.replace("{repo}", repo);
    if (!confirm(msg)) return;
    try {
      await del.mutateAsync(repo);
      toast("success", t.sync.deleteSuccess);
      refetchSchedules();
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError));
    }
  }

  async function handleTrigger(repo: string) {
    try {
      await trigger.mutateAsync(repo);
      toast("success", t.sync.triggerSuccess);
      refetchSchedules();
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError) || t.sync.triggerFailed);
    }
  }

  function statusLabel(s: string) {
    if (s === "success") return t.sync.statusSuccess;
    if (s === "failed") return t.sync.statusFailed;
    return t.sync.statusPending;
  }

  function formatWhen(iso: string | null) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString(locale === "zh" ? "zh-CN" : undefined);
    } catch {
      return iso;
    }
  }

  const inputClass =
    "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600";

  const schedules = schedulesData?.schedules ?? [];
  const indexedRepos = reposData?.repositories ?? [];

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
              className={inputClass}
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

      {isAdmin && (
        <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Webhook size={18} className="text-gray-500 dark:text-gray-400" />
              <h3 className="text-sm font-medium text-gray-800 dark:text-gray-100">
                {t.webhook.title}
              </h3>
            </div>
            <button
              type="button"
              onClick={openWebhookModal}
              disabled={webhookLoading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
            >
              <Pencil size={14} /> {t.webhook.editConfig}
            </button>
          </div>

          {webhookError && (
            <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
              {getErrorMessage(webhookError, t.common.unexpectedError) || t.webhook.loadFailed}
            </div>
          )}

          {webhookLoading ? (
            <div className="mt-4 space-y-3">
              <SkeletonLine className="h-4 w-full max-w-md" />
              <SkeletonLine className="h-4 w-48" />
              <SkeletonLine className="h-20 w-full" />
            </div>
          ) : webhookConfig ? (
            <div className="mt-4 space-y-4 text-sm">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-3 dark:border-gray-700">
                <span className="text-gray-500 dark:text-gray-400">{t.webhook.masterSwitch}</span>
                <span
                  className={
                    webhookConfig.enabled
                      ? "font-medium text-emerald-600 dark:text-emerald-400"
                      : "font-medium text-gray-500 dark:text-gray-400"
                  }
                >
                  {webhookConfig.enabled ? t.webhook.labelEnabled : t.webhook.labelDisabled}
                </span>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-gray-500 dark:text-gray-400">{t.webhook.debounceSeconds}</span>
                <span className="text-gray-800 dark:text-gray-100">{webhookConfig.debounce_seconds}</span>
              </div>
              <div>
                <div className="text-gray-500 dark:text-gray-400">{t.webhook.autoUpdateBranches}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {(webhookConfig.auto_update_branches?.length ?? 0) === 0 ? (
                    <span className="text-gray-400">—</span>
                  ) : (
                    webhookConfig.auto_update_branches.map((b) => (
                      <span
                        key={b}
                        className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300"
                      >
                        {b}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[480px] text-left text-sm">
                  <thead className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/80">
                    <tr>
                      <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">
                        {t.webhook.colProvider}
                      </th>
                      <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">
                        {t.webhook.colSecret}
                      </th>
                      <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">
                        {t.webhook.colSwitch}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {WEBHOOK_PROVIDERS.map((key) => {
                      const secret = webhookConfig.providers?.[key]?.secret;
                      const configured = !!(secret && String(secret).trim());
                      const label =
                        key === "github"
                          ? t.webhook.providerGithub
                          : key === "gitlab"
                            ? t.webhook.providerGitlab
                            : t.webhook.providerGitea;
                      return (
                        <tr key={key} className="border-b border-gray-100 dark:border-gray-800">
                          <td className="px-3 py-2 font-medium text-gray-800 dark:text-gray-100">{label}</td>
                          <td className="px-3 py-2 text-gray-700 dark:text-gray-300">
                            {configured ? t.webhook.secretConfigured : t.webhook.secretNotConfigured}
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded border-gray-300 text-sky-600 focus:ring-sky-500 dark:border-gray-600"
                              checked={webhookConfig.enabled}
                              readOnly
                              disabled
                              title={t.webhook.globalToggleTitle}
                            />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ) : !webhookError ? (
            <p className="mt-4 text-sm text-gray-400 dark:text-gray-500">
              {t.webhook.noConfigData}
            </p>
          ) : null}
        </div>
      )}

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

      <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Clock size={18} className="text-gray-500 dark:text-gray-400" />
            <div>
              <h3 className="text-sm font-medium text-gray-800 dark:text-gray-100">{t.sync.title}</h3>
              <p className="text-xs text-gray-500 dark:text-gray-400">{t.sync.description}</p>
            </div>
          </div>
          {isAdmin && (
            <button
              type="button"
              onClick={openAdd}
              className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500"
            >
              <Plus size={14} /> {t.sync.addSchedule}
            </button>
          )}
        </div>

        {!authLoading && !isAdmin && (
          <p className="mt-4 text-sm text-amber-700 dark:text-amber-300">{t.sync.adminOnly}</p>
        )}

        {isAdmin && schedulesError && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-600 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-400">
            {getErrorMessage(schedulesError, t.common.unexpectedError) || t.sync.loadFailed}
          </div>
        )}

        {isAdmin && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[880px] text-left text-sm">
              <thead className="border-b border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/80">
                <tr>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.repoName}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.gitUrl}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.branch}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.intervalMinutes}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.enabled}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.lastSync}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.status}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.detail}</th>
                  <th className="px-3 py-2 font-medium text-gray-500 dark:text-gray-400">{t.sync.actions}</th>
                </tr>
              </thead>
              <tbody>
                {schedulesLoading ? (
                  Array.from({ length: 2 }).map((_, i) => (
                    <tr key={i} className="border-b border-gray-100 dark:border-gray-800">
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-28" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-48" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-16" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-10" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-10" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-24" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-16" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-32" />
                      </td>
                      <td className="px-3 py-2">
                        <SkeletonLine className="h-4 w-20" />
                      </td>
                    </tr>
                  ))
                ) : schedules.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-gray-400 dark:text-gray-500">
                      {t.sync.noSchedules}
                    </td>
                  </tr>
                ) : (
                  schedules.map((row) => (
                    <tr key={schedulePath(row.repo_name)} className="border-b border-gray-100 hover:bg-gray-50/80 dark:border-gray-800 dark:hover:bg-gray-800/50">
                      <td className="px-3 py-2 font-medium text-gray-800 dark:text-gray-100">{row.repo_name}</td>
                      <td className="max-w-[200px] truncate px-3 py-2 text-gray-600 dark:text-gray-400" title={row.git_url}>
                        {row.git_url}
                      </td>
                      <td className="px-3 py-2 text-gray-600 dark:text-gray-400">{row.branch ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-600 dark:text-gray-400">{row.interval_minutes}</td>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-gray-300 text-sky-600 focus:ring-sky-500 dark:border-gray-600"
                          checked={row.enabled}
                          disabled={upsert.isPending}
                          onChange={(e) => handleToggleEnabled(row, e.target.checked)}
                        />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-600 dark:text-gray-400">
                        {formatWhen(row.last_sync_at)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={
                            row.last_sync_status === "success"
                              ? "text-emerald-600 dark:text-emerald-400"
                              : row.last_sync_status === "failed"
                                ? "text-red-600 dark:text-red-400"
                                : "text-amber-600 dark:text-amber-400"
                          }
                        >
                          {statusLabel(row.last_sync_status)}
                        </span>
                      </td>
                      <td
                        className="max-w-[180px] truncate px-3 py-2 text-xs text-gray-500 dark:text-gray-400"
                        title={row.last_sync_detail || undefined}
                      >
                        {row.last_sync_detail || "—"}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          <button
                            type="button"
                            onClick={() => openEdit(row)}
                            className="inline-flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
                          >
                            <Pencil size={12} /> {t.sync.edit}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleTrigger(row.repo_name)}
                            disabled={trigger.isPending}
                            className="inline-flex items-center gap-1 rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-700 hover:bg-sky-100 disabled:opacity-50 dark:border-sky-800 dark:bg-sky-950/50 dark:text-sky-300 dark:hover:bg-sky-950"
                          >
                            {trigger.isPending ? (
                              <Loader2 size={12} className="animate-spin" />
                            ) : (
                              <RefreshCw size={12} />
                            )}
                            {t.sync.triggerNow}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDelete(row.repo_name)}
                            disabled={del.isPending}
                            className="inline-flex items-center gap-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700 hover:bg-red-100 disabled:opacity-50 dark:border-red-900/60 dark:bg-red-950/40 dark:text-red-300 dark:hover:bg-red-950/60"
                          >
                            <Trash2 size={12} /> {t.sync.delete}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 dark:bg-black/60" role="dialog" aria-modal="true" aria-labelledby="schedule-modal-title">
          <FocusTrap onEscape={closeModal}>
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-gray-200 bg-white p-5 shadow-xl dark:border-gray-600 dark:bg-gray-900 dark:shadow-gray-950/50">
            <h4 id="schedule-modal-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {editing ? t.sync.editSchedule : t.sync.addSchedule}
            </h4>
            <form onSubmit={submitModal} className="mt-4 space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.selectRepo}</label>
                <select
                  className={`${inputClass} mt-1`}
                  value=""
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v) setFormRepo(v);
                  }}
                >
                  <option value="">—</option>
                  {indexedRepos.map((r) => (
                    <option key={r.repository} value={r.repository}>
                      {r.repository}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.repoName}</label>
                <input
                  className={`${inputClass} mt-1`}
                  value={formRepo}
                  onChange={(e) => setFormRepo(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.gitUrl}</label>
                <input
                  className={`${inputClass} mt-1`}
                  value={formGitUrl}
                  onChange={(e) => setFormGitUrl(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.branch}</label>
                <input
                  className={`${inputClass} mt-1`}
                  placeholder={t.sync.branchPlaceholder}
                  value={formBranch}
                  onChange={(e) => setFormBranch(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.intervalMinutes}</label>
                <input
                  type="number"
                  min={5}
                  max={1440}
                  className={`${inputClass} mt-1`}
                  value={formInterval}
                  onChange={(e) => setFormInterval(Number(e.target.value))}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-gray-300 text-sky-600 dark:border-gray-600"
                  checked={formEnabled}
                  onChange={(e) => setFormEnabled(e.target.checked)}
                />
                {t.sync.enabled}
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeModal}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                >
                  {t.sync.cancel}
                </button>
                <button
                  type="submit"
                  disabled={upsert.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
                >
                  {upsert.isPending ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
                  {t.sync.save}
                </button>
              </div>
            </form>
          </div>
          </FocusTrap>
        </div>
      )}

      {webhookModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 dark:bg-black/60" role="dialog" aria-modal="true" aria-labelledby="webhook-modal-title">
          <FocusTrap onEscape={closeWebhookModal}>
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-gray-200 bg-white p-5 shadow-xl dark:border-gray-600 dark:bg-gray-900 dark:shadow-gray-950/50">
            <h4 id="webhook-modal-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {t.webhook.modalTitle}
            </h4>
            <form onSubmit={submitWebhookModal} className="mt-4 space-y-3">
              <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-gray-300 text-sky-600 dark:border-gray-600"
                  checked={whEnabled}
                  onChange={(e) => setWhEnabled(e.target.checked)}
                />
                {t.webhook.enableWebhooks}
              </label>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t.webhook.debounceLabel}
                </label>
                <input
                  type="number"
                  min={1}
                  max={86400}
                  className={`${inputClass} mt-1`}
                  value={whDebounce}
                  onChange={(e) => setWhDebounce(Number(e.target.value))}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">
                  {t.webhook.branchesLabel}
                </label>
                <input
                  className={`${inputClass} mt-1`}
                  value={whBranches}
                  onChange={(e) => setWhBranches(e.target.value)}
                  placeholder={t.webhook.branchesPlaceholder}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.webhook.secretGithub}</label>
                <input
                  type="password"
                  className={`${inputClass} mt-1`}
                  value={whSecretGithub}
                  onChange={(e) => setWhSecretGithub(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.webhook.secretGitlab}</label>
                <input
                  type="password"
                  className={`${inputClass} mt-1`}
                  value={whSecretGitlab}
                  onChange={(e) => setWhSecretGitlab(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.webhook.secretGitea}</label>
                <input
                  type="password"
                  className={`${inputClass} mt-1`}
                  value={whSecretGitea}
                  onChange={(e) => setWhSecretGitea(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeWebhookModal}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-800"
                >
                  {t.sync.cancel}
                </button>
                <button
                  type="submit"
                  disabled={updateWebhook.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
                >
                  {updateWebhook.isPending ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Save size={14} />
                  )}
                  {t.sync.save}
                </button>
              </div>
            </form>
          </div>
          </FocusTrap>
        </div>
      )}
        </div>
      ) : null}
    </div>
  );
}
