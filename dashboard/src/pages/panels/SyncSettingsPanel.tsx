import { useState } from "react";
import FocusTrap from "../../components/FocusTrap";
import { Clock, Plus, Pencil, Trash2, RefreshCw, Loader2, Save } from "lucide-react";
import {
  useRepositories,
  useSyncSchedules,
  useCreateSyncSchedule,
  useDeleteSyncSchedule,
  useTriggerSync,
} from "../../api/hooks";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import { useToast } from "../../components/Toast";
import type { SyncSchedule, SyncScheduleRequest } from "../../api/types";
import { useAuth } from "../../contexts/AuthContext";
import { SkeletonLine } from "../../components/Skeleton";
import { SETTINGS_INPUT_CLASS } from "./settingsInputClass";

function schedulePath(repo: string) {
  return repo.split("/").map(encodeURIComponent).join("/");
}

export default function SyncSettingsPanel() {
  const { t, locale } = useI18n();
  const { toast } = useToast();
  const { isAdmin, isLoading: authLoading } = useAuth();

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

  const schedules = schedulesData?.schedules ?? [];
  const indexedRepos = reposData?.repositories ?? [];

  return (
    <>
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
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
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
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
                  value={formRepo}
                  onChange={(e) => setFormRepo(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.gitUrl}</label>
                <input
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
                  value={formGitUrl}
                  onChange={(e) => setFormGitUrl(e.target.value)}
                  required
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{t.sync.branch}</label>
                <input
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
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
                  className={`${SETTINGS_INPUT_CLASS} mt-1`}
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
    </>
  );
}
