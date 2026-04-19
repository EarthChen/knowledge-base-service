import { useState } from "react";
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
import { useToast } from "../components/Toast";
import type { Locale } from "../i18n/types";
import type { SyncSchedule, SyncScheduleRequest, WebhookConfig } from "../api/types";
import { useAuth } from "../contexts/AuthContext";
import { SkeletonLine } from "../components/Skeleton";

const LOCALE_OPTIONS: { value: Locale; label: string }[] = [
  { value: "en", label: "English" },
  { value: "zh", label: "简体中文" },
];

function schedulePath(repo: string) {
  return repo.split("/").map(encodeURIComponent).join("/");
}

const WEBHOOK_PROVIDERS = ["github", "gitlab", "gitea"] as const;

export default function SettingsPage() {
  const [tokenValue, setTokenValue] = useState(getToken());
  const [showToken, setShowToken] = useState(false);
  const { data: health, refetch } = useHealth();
  const { t, locale, setLocale } = useI18n();
  const { toast } = useToast();
  const { isAdmin, isLoading: authLoading } = useAuth();
  const isZh = locale === "zh";

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
      toast("success", isZh ? "Webhook 配置已保存" : "Webhook configuration saved");
      closeWebhookModal();
      refetchWebhook();
    } catch (err) {
      toast("error", (err as Error).message);
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
      toast("error", (err as Error).message);
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
      toast("error", (err as Error).message);
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
      toast("error", (err as Error).message);
    }
  }

  async function handleTrigger(repo: string) {
    try {
      await trigger.mutateAsync(repo);
      toast("success", t.sync.triggerSuccess);
      refetchSchedules();
    } catch (err) {
      toast("error", (err as Error).message || t.sync.triggerFailed);
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
    "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300";

  const schedules = schedulesData?.schedules ?? [];
  const indexedRepos = reposData?.repositories ?? [];

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <Settings size={20} /> {t.settings.title}
      </h2>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex items-center gap-2">
          <Globe size={16} className="text-gray-500" />
          <h3 className="text-sm font-medium text-gray-700">{t.settings.language}</h3>
        </div>
        <div className="mt-3 flex gap-2">
          {LOCALE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setLocale(opt.value)}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                locale === opt.value
                  ? "bg-sky-100 text-sky-600"
                  : "border border-gray-300 text-gray-500 hover:text-gray-700"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-medium text-gray-700">{t.settings.apiToken}</h3>
        <p className="mt-1 text-xs text-gray-400">
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
              className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700"
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

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <h3 className="text-sm font-medium text-gray-700">{t.settings.serviceInfo}</h3>
        <div className="mt-3 space-y-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-gray-400">{t.settings.health}</span>
            <span className={health?.status === "ok" ? "text-emerald-600" : "text-amber-600"}>
              {health?.status === "ok" ? t.sidebar.healthy : t.sidebar.unreachable}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">{t.settings.apiBase}</span>
            <span className="font-mono text-xs text-gray-700">/api/v1</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-gray-400">{t.settings.deployment}</span>
            <span className="text-gray-700">{t.settings.deploymentValue}</span>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex items-center gap-2">
          <BookOpen size={16} className="text-gray-500" />
          <h3 className="text-sm font-medium text-gray-700">
            {isZh ? "Wiki 配置（只读）" : "Wiki configuration (read-only)"}
          </h3>
        </div>
        <p className="mt-1 text-xs text-gray-500">
          {isZh
            ? "链式思考（CoT）与模型名称来自服务端环境变量，由 /health 返回。"
            : "Chain-of-thought (CoT) flags and model names come from server environment variables via /health."}
        </p>
        <div className="mt-4 space-y-4 text-sm">
          {!health?.wiki ? (
            <p className="text-gray-500">
              {isZh
                ? "当前服务未在健康检查中返回 wiki 字段（可能为旧版本）。"
                : "Health response has no wiki section (server may be an older build)."}
            </p>
          ) : (
            <>
              <label className="flex cursor-not-allowed items-center justify-between gap-3 rounded-lg border border-gray-100 bg-gray-50/80 px-3 py-2 opacity-90">
                <span className="text-gray-600">{isZh ? "启用 CoT" : "CoT enabled"}</span>
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-gray-300 text-sky-600"
                  checked={health.wiki.cot_enabled}
                  readOnly
                  disabled
                  aria-readonly
                />
              </label>
              <div className="space-y-1">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  {isZh ? "CoT 分析模型" : "CoT analysis model"}
                </div>
                <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 font-mono text-xs text-gray-800">
                  {health.wiki.cot_analysis_model?.trim()
                    ? health.wiki.cot_analysis_model
                    : isZh
                      ? "（未设置）"
                      : "(not set)"}
                </div>
              </div>
              <div className="space-y-1">
                <div className="text-xs font-medium uppercase tracking-wide text-gray-500">
                  {isZh ? "CoT 生成模型" : "CoT generation model"}
                </div>
                <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 font-mono text-xs text-gray-800">
                  {health.wiki.cot_generation_model?.trim()
                    ? health.wiki.cot_generation_model
                    : isZh
                      ? "（未设置）"
                      : "(not set)"}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {isAdmin && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <Webhook size={18} className="text-gray-500" />
              <h3 className="text-sm font-medium text-gray-800">
                {isZh ? "Webhook 配置" : "Webhook Configuration"}
              </h3>
            </div>
            <button
              type="button"
              onClick={openWebhookModal}
              disabled={webhookLoading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              <Pencil size={14} /> {isZh ? "编辑配置" : "Edit configuration"}
            </button>
          </div>

          {webhookError && (
            <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-600">
              {(webhookError as Error).message ||
                (isZh ? "加载 Webhook 配置失败" : "Failed to load webhook configuration")}
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
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-gray-100 pb-3">
                <span className="text-gray-500">{isZh ? "总开关" : "Master switch"}</span>
                <span
                  className={
                    webhookConfig.enabled ? "font-medium text-emerald-600" : "font-medium text-gray-500"
                  }
                >
                  {webhookConfig.enabled
                    ? isZh
                      ? "已启用"
                      : "Enabled"
                    : isZh
                      ? "已禁用"
                      : "Disabled"}
                </span>
              </div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-gray-500">{isZh ? "防抖（秒）" : "Debounce (seconds)"}</span>
                <span className="text-gray-800">{webhookConfig.debounce_seconds}</span>
              </div>
              <div>
                <div className="text-gray-500">{isZh ? "自动更新分支" : "Auto-update branches"}</div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {(webhookConfig.auto_update_branches?.length ?? 0) === 0 ? (
                    <span className="text-gray-400">—</span>
                  ) : (
                    webhookConfig.auto_update_branches.map((b) => (
                      <span
                        key={b}
                        className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700"
                      >
                        {b}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[480px] text-left text-sm">
                  <thead className="border-b border-gray-200 bg-gray-50">
                    <tr>
                      <th className="px-3 py-2 font-medium text-gray-500">
                        {isZh ? "提供商" : "Provider"}
                      </th>
                      <th className="px-3 py-2 font-medium text-gray-500">
                        {isZh ? "密钥" : "Secret"}
                      </th>
                      <th className="px-3 py-2 font-medium text-gray-500">
                        {isZh ? "开关" : "Switch"}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {WEBHOOK_PROVIDERS.map((key) => {
                      const secret = webhookConfig.providers?.[key]?.secret;
                      const configured = !!(secret && String(secret).trim());
                      const label =
                        key === "github" ? "GitHub" : key === "gitlab" ? "GitLab" : "Gitea";
                      return (
                        <tr key={key} className="border-b border-gray-100">
                          <td className="px-3 py-2 font-medium text-gray-800">{label}</td>
                          <td className="px-3 py-2 text-gray-700">
                            {configured
                              ? "***configured***"
                              : isZh
                                ? "未配置"
                                : "Not configured"}
                          </td>
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded border-gray-300 text-sky-600 focus:ring-sky-500"
                              checked={webhookConfig.enabled}
                              readOnly
                              disabled
                              title={
                                isZh
                                  ? "Webhook 总开关状态（在编辑中修改）"
                                  : "Global webhook toggle (edit in modal)"
                              }
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
            <p className="mt-4 text-sm text-gray-400">
              {isZh ? "暂无配置数据" : "No configuration loaded"}
            </p>
          ) : null}
        </div>
      )}

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex items-center gap-2">
          <CalendarClock size={18} className="text-gray-500" />
          <h3 className="text-sm font-medium text-gray-800">
            {isZh ? "Wiki 定时再生成" : "Wiki Scheduled Regeneration"}
          </h3>
        </div>
        <p className="mt-2 text-xs text-gray-500">
          {isZh
            ? "由 P3 Webhook 与调度器（Scheduler）功能协同驱动 Wiki 内容的定时与事件触发更新。"
            : "Driven by P3 Webhook and Scheduler features for timed and event-triggered wiki updates."}
        </p>
        <div className="mt-4 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-sm text-gray-700">
          {isZh
            ? "由 Webhook 事件触发或按计划自动执行"
            : "Triggered by webhook events or runs on schedule"}
        </div>
        <p className="mt-3 text-xs text-amber-800">
          {isZh
            ? "提示：当 Webhook 启用时，代码推送会自动触发增量更新。"
            : "Tip: When webhooks are enabled, code pushes trigger incremental updates automatically."}
        </p>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Clock size={18} className="text-gray-500" />
            <div>
              <h3 className="text-sm font-medium text-gray-800">{t.sync.title}</h3>
              <p className="text-xs text-gray-500">{t.sync.description}</p>
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
          <p className="mt-4 text-sm text-amber-700">{t.sync.adminOnly}</p>
        )}

        {isAdmin && schedulesError && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-600">
            {(schedulesError as Error).message || t.sync.loadFailed}
          </div>
        )}

        {isAdmin && (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[880px] text-left text-sm">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.repoName}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.gitUrl}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.branch}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.intervalMinutes}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.enabled}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.lastSync}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.status}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.detail}</th>
                  <th className="px-3 py-2 font-medium text-gray-500">{t.sync.actions}</th>
                </tr>
              </thead>
              <tbody>
                {schedulesLoading ? (
                  Array.from({ length: 2 }).map((_, i) => (
                    <tr key={i} className="border-b border-gray-100">
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
                    <td colSpan={9} className="px-3 py-8 text-center text-gray-400">
                      {t.sync.noSchedules}
                    </td>
                  </tr>
                ) : (
                  schedules.map((row) => (
                    <tr key={schedulePath(row.repo_name)} className="border-b border-gray-100 hover:bg-gray-50/80">
                      <td className="px-3 py-2 font-medium text-gray-800">{row.repo_name}</td>
                      <td className="max-w-[200px] truncate px-3 py-2 text-gray-600" title={row.git_url}>
                        {row.git_url}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{row.branch ?? "—"}</td>
                      <td className="px-3 py-2 text-gray-600">{row.interval_minutes}</td>
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-gray-300 text-sky-600 focus:ring-sky-500"
                          checked={row.enabled}
                          disabled={upsert.isPending}
                          onChange={(e) => handleToggleEnabled(row, e.target.checked)}
                        />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-600">
                        {formatWhen(row.last_sync_at)}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={
                            row.last_sync_status === "success"
                              ? "text-emerald-600"
                              : row.last_sync_status === "failed"
                                ? "text-red-600"
                                : "text-amber-600"
                          }
                        >
                          {statusLabel(row.last_sync_status)}
                        </span>
                      </td>
                      <td
                        className="max-w-[180px] truncate px-3 py-2 text-xs text-gray-500"
                        title={row.last_sync_detail || undefined}
                      >
                        {row.last_sync_detail || "—"}
                      </td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap gap-1">
                          <button
                            type="button"
                            onClick={() => openEdit(row)}
                            className="inline-flex items-center gap-1 rounded border border-gray-200 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
                          >
                            <Pencil size={12} /> {t.sync.edit}
                          </button>
                          <button
                            type="button"
                            onClick={() => handleTrigger(row.repo_name)}
                            disabled={trigger.isPending}
                            className="inline-flex items-center gap-1 rounded border border-sky-200 bg-sky-50 px-2 py-1 text-xs text-sky-700 hover:bg-sky-100 disabled:opacity-50"
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
                            className="inline-flex items-center gap-1 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700 hover:bg-red-100 disabled:opacity-50"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="schedule-modal-title">
          <FocusTrap onEscape={closeModal}>
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-gray-200 bg-white p-5 shadow-xl">
            <h4 id="schedule-modal-title" className="text-base font-semibold text-gray-900">
              {editing ? t.sync.editSchedule : t.sync.addSchedule}
            </h4>
            <form onSubmit={submitModal} className="mt-4 space-y-3">
              <div>
                <label className="text-xs font-medium text-gray-600">{t.sync.selectRepo}</label>
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
                <label className="text-xs font-medium text-gray-600">{t.sync.repoName}</label>
                <input
                  className={`${inputClass} mt-1`}
                  value={formRepo}
                  onChange={(e) => setFormRepo(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">{t.sync.gitUrl}</label>
                <input
                  className={`${inputClass} mt-1`}
                  value={formGitUrl}
                  onChange={(e) => setFormGitUrl(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">{t.sync.branch}</label>
                <input
                  className={`${inputClass} mt-1`}
                  placeholder={t.sync.branchPlaceholder}
                  value={formBranch}
                  onChange={(e) => setFormBranch(e.target.value)}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">{t.sync.intervalMinutes}</label>
                <input
                  type="number"
                  min={5}
                  max={1440}
                  className={`${inputClass} mt-1`}
                  value={formInterval}
                  onChange={(e) => setFormInterval(Number(e.target.value))}
                />
              </div>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-gray-300 text-sky-600"
                  checked={formEnabled}
                  onChange={(e) => setFormEnabled(e.target.checked)}
                />
                {t.sync.enabled}
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={closeModal}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  {t.sync.cancel}
                </button>
                <button
                  type="submit"
                  disabled={upsert.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="webhook-modal-title">
          <FocusTrap onEscape={closeWebhookModal}>
          <div className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl border border-gray-200 bg-white p-5 shadow-xl">
            <h4 id="webhook-modal-title" className="text-base font-semibold text-gray-900">
              {isZh ? "编辑 Webhook 配置" : "Edit webhook configuration"}
            </h4>
            <form onSubmit={submitWebhookModal} className="mt-4 space-y-3">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-gray-300 text-sky-600"
                  checked={whEnabled}
                  onChange={(e) => setWhEnabled(e.target.checked)}
                />
                {isZh ? "启用 Webhook（总开关）" : "Enable webhooks (master switch)"}
              </label>
              <div>
                <label className="text-xs font-medium text-gray-600">
                  {isZh ? "防抖间隔（秒，1–86400）" : "Debounce seconds (1–86400)"}
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
                <label className="text-xs font-medium text-gray-600">
                  {isZh ? "自动更新分支（逗号分隔）" : "Auto-update branches (comma-separated)"}
                </label>
                <input
                  className={`${inputClass} mt-1`}
                  value={whBranches}
                  onChange={(e) => setWhBranches(e.target.value)}
                  placeholder={isZh ? "例如 main, develop" : "e.g. main, develop"}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">GitHub secret</label>
                <input
                  type="password"
                  className={`${inputClass} mt-1`}
                  value={whSecretGithub}
                  onChange={(e) => setWhSecretGithub(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">GitLab secret</label>
                <input
                  type="password"
                  className={`${inputClass} mt-1`}
                  value={whSecretGitlab}
                  onChange={(e) => setWhSecretGitlab(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600">Gitea secret</label>
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
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
                >
                  {t.sync.cancel}
                </button>
                <button
                  type="submit"
                  disabled={updateWebhook.isPending}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
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
  );
}
