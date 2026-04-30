import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, XCircle, AlertTriangle } from "lucide-react";
import { cancelWikiTask, listActiveWikiTasks } from "../../api/client";
import type { WikiAsyncTask } from "../../api/types";
import { useI18n } from "../../i18n/context";
import { useToast } from "../Toast";

type PhaseKey = "leaf_compose" | "parent_aggregate" | "business_flow" | "navigation" | "quality_eval";
const phaseI18nKeys: Record<PhaseKey, keyof typeof import("../../i18n/en").default.wiki> = {
  leaf_compose: "phaseLeafCompose",
  parent_aggregate: "phaseParentAggregate",
  business_flow: "phaseBusinessFlow",
  navigation: "phaseNavigation",
  quality_eval: "phaseQualityEval",
};

interface WikiActiveTasksProps {
  businessId: string;
}

export default function WikiActiveTasks({ businessId }: WikiActiveTasksProps) {
  const [tasks, setTasks] = useState<WikiAsyncTask[]>([]);
  const [confirmingCancel, setConfirmingCancel] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const { t } = useI18n();
  const { toast } = useToast();

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const fetchTasks = useCallback(async () => {
    try {
      const res = await listActiveWikiTasks();
      if (!mountedRef.current) return;
      setTasks(res.tasks.filter((tk) => ["pending", "queued", "running"].includes(tk.status)));
    } catch {
      // silently ignore polling errors
    }
  }, []);

  useEffect(() => {
    void fetchTasks();
    const id = setInterval(() => void fetchTasks(), 5000);
    return () => clearInterval(id);
  }, [fetchTasks]);

  const handleCancelClick = useCallback((taskId: string) => {
    setConfirmingCancel(taskId);
  }, []);

  const handleCancelConfirm = useCallback(
    async (taskId: string) => {
      setCancelling(taskId);
      setConfirmingCancel(null);
      try {
        await cancelWikiTask(taskId);
        if (!mountedRef.current) return;
        toast("success", t.wiki.taskCancelled);
        setTasks((prev) => prev.filter((tk) => tk.task_id !== taskId));
      } catch {
        if (mountedRef.current) toast("error", t.wiki.taskCancelFailed);
      } finally {
        if (mountedRef.current) setCancelling(null);
      }
    },
    [t, toast],
  );

  const handleCancelDismiss = useCallback(() => {
    setConfirmingCancel(null);
  }, []);

  const relevantTasks = tasks.filter(
    (tk) => !tk.business_id || tk.business_id === businessId || tk.business_id === "default",
  );

  if (relevantTasks.length === 0) return null;

  return (
    <div className="space-y-2">
      {relevantTasks.map((task) => {
        const pct = Number(task.progress_pct) || 0;
        const currentRepo = task.current_repo ?? "";
        const isConfirming = confirmingCancel === task.task_id;
        const isCancelling = cancelling === task.task_id;

        return (
          <div
            key={task.task_id}
            className="rounded-lg border border-sky-200/80 bg-sky-50/50 px-3 py-2 dark:border-sky-900/50 dark:bg-sky-950/20"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-xs text-sky-900 dark:text-sky-100">
                <Loader2 size={14} className="shrink-0 animate-spin" />
                <span className="font-medium">{t.wiki.activeTaskLabel}</span>
                <span className="text-sky-700 dark:text-sky-300">
                  {task.task_id.slice(0, 16)}…
                </span>
              </div>

              {isConfirming ? (
                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-amber-700 dark:text-amber-300">
                    {t.wiki.taskCancelConfirm}
                  </span>
                  <button
                    type="button"
                    onClick={() => void handleCancelConfirm(task.task_id)}
                    className="rounded border border-red-300 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-800 dark:bg-red-950/50 dark:text-red-300 dark:hover:bg-red-950"
                  >
                    {t.wiki.taskCancelYes}
                  </button>
                  <button
                    type="button"
                    onClick={handleCancelDismiss}
                    className="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700"
                  >
                    {t.wiki.taskCancelNo}
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => handleCancelClick(task.task_id)}
                  disabled={isCancelling}
                  className="inline-flex items-center gap-1 rounded border border-gray-200 bg-white px-2 py-0.5 text-xs text-gray-600 hover:border-red-300 hover:bg-red-50 hover:text-red-700 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:border-red-800 dark:hover:bg-red-950/50 dark:hover:text-red-300"
                >
                  {isCancelling ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <XCircle size={12} />
                  )}
                  {t.wiki.taskCancel}
                </button>
              )}
            </div>

            {currentRepo && (
              <p className="mt-1 text-xs text-sky-700 dark:text-sky-300">
                {t.wiki.activeTaskProgress
                  .replace("{current}", currentRepo)
                  .replace("{pct}", String(Math.round(pct)))}
              </p>
            )}

            {task.current_phase && (
              <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {phaseI18nKeys[task.current_phase as PhaseKey]
                  ? t.wiki[phaseI18nKeys[task.current_phase as PhaseKey]]
                  : task.current_phase}
              </div>
            )}

            {pct > 0 && (
              <div
                className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-sky-200 dark:bg-sky-800"
                role="progressbar"
                aria-valuenow={Math.round(pct)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div
                  className="h-full rounded-full bg-sky-500 transition-[width] dark:bg-sky-400"
                  style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                />
              </div>
            )}

            {(task.status === "pending" || task.status === "queued") && !currentRepo && (
              <p className="mt-1 flex items-center gap-1 text-xs text-sky-600 dark:text-sky-400">
                <AlertTriangle size={12} />
                {t.wiki.activeTaskPending}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
