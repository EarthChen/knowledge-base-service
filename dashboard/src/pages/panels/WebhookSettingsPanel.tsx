import { useState } from "react";
import FocusTrap from "../../components/FocusTrap";
import { Pencil, Webhook, Loader2, Save } from "lucide-react";
import { useUpdateWebhookConfig, useWebhookConfig } from "../../api/hooks";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import { useToast } from "../../components/Toast";
import type { WebhookConfig } from "../../api/types";
import { useAuth } from "../../contexts/AuthContext";
import { SkeletonLine } from "../../components/Skeleton";
import { SETTINGS_INPUT_CLASS } from "./settingsInputClass";

const WEBHOOK_PROVIDERS = ["github", "gitlab", "gitea"] as const;

export default function WebhookSettingsPanel() {
  const { t } = useI18n();
  const { toast } = useToast();
  const { isAdmin, isLoading: authLoading } = useAuth();

  const {
    data: webhookConfig,
    isLoading: webhookLoading,
    error: webhookError,
    refetch: refetchWebhook,
  } = useWebhookConfig({ enabled: isAdmin && !authLoading });
  const updateWebhook = useUpdateWebhookConfig();

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
      const existing = base?.providers?.[provider as "github" | "gitlab" | "gitea"]?.secret ?? "";
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

  if (!isAdmin) return null;

  return (
    <>
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
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
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
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
                  value={whBranches}
                  onChange={(e) => setWhBranches(e.target.value)}
                  placeholder={t.webhook.branchesPlaceholder}
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.webhook.secretGithub}</label>
                <input
                  type="password"
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
                  value={whSecretGithub}
                  onChange={(e) => setWhSecretGithub(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.webhook.secretGitlab}</label>
                <input
                  type="password"
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
                  value={whSecretGitlab}
                  onChange={(e) => setWhSecretGitlab(e.target.value)}
                  autoComplete="new-password"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.webhook.secretGitea}</label>
                <input
                  type="password"
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
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
    </>
  );
}
