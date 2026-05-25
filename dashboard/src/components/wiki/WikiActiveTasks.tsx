import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, XCircle, AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { cancelWikiTask, listActiveWikiTasks } from "../../api/client";
import type { WikiAsyncTask } from "../../api/types";
import type { Translations } from "../../i18n/types";
import { useI18n } from "../../i18n/context";
import { useToast } from "../Toast";
import WikiPipelineVisualization from "./WikiPipelineVisualization";

type WikiPhaseTranslationKey =
  | "phaseClassifyEntities"
  | "phaseClassifyDomains"
  | "phaseComposeLeafModules"
  | "phaseComposeLeaf"
  | "phaseQualityGate"
  | "phaseParentAggregate"
  | "phaseOverview"
  | "phaseLinking"
  | "phaseFinalize"
  | "phaseLeafCompose"
  | "phaseBusinessFlow"
  | "phaseNavigation"
  | "phaseQualityEval"
  | "phaseClassifyingDomains"
  | "phasePersistingPages"
  | "phaseGeneratingPages";

const phaseI18nKeys: Record<string, WikiPhaseTranslationKey> = {
  classify_entities: "phaseClassifyEntities",
  graph_domain_decompose: "phaseClassifyDomains",
  compose_leaf_modules: "phaseComposeLeafModules",
  compose_leaf: "phaseComposeLeaf",
  quality_gate: "phaseQualityGate",
  parent_aggregate: "phaseParentAggregate",
  overview: "phaseOverview",
  linking: "phaseLinking",
  finalize: "phaseFinalize",
  leaf_compose: "phaseLeafCompose",
  business_flow: "phaseBusinessFlow",
  navigation: "phaseNavigation",
  quality_eval: "phaseQualityEval",
  classifying_domains: "phaseClassifyingDomains",
  persisting_pages: "phasePersistingPages",
  generating_pages: "phaseGeneratingPages",
};

function wikiPhaseLabel(wiki: Translations["wiki"], phaseId: string): string {
  const key = phaseI18nKeys[phaseId];
  return key ? wiki[key] : phaseId;
}

interface WikiActiveTasksProps {
  businessId: string;
}

const POLL_FAIL_THRESHOLD = 3;

export default function WikiActiveTasks({ businessId }: WikiActiveTasksProps) {
  const [tasks, setTasks] = useState<WikiAsyncTask[]>([]);
  const [pollFailed, setPollFailed] = useState(false);
  const [confirmingCancel, setConfirmingCancel] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [expandedPipeline, setExpandedPipeline] = useState<Record<string, boolean>>({});
  const mountedRef = useRef(true);
  const pollFailCountRef = useRef(0);
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
      pollFailCountRef.current = 0;
      setPollFailed(false);
      setTasks(res.tasks.filter((tk) => ["pending", "queued", "running"].includes(tk.status)));
    } catch {
      if (!mountedRef.current) return;
      pollFailCountRef.current += 1;
      if (pollFailCountRef.current >= POLL_FAIL_THRESHOLD) {
        setPollFailed(true);
      }
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

  if (relevantTasks.length === 0 && !pollFailed) return null;

  return (
    <div className="space-y-2">
      {pollFailed && (
        <p
          className="flex items-center gap-1.5 rounded-lg border border-amber-200/80 bg-amber-50/60 px-2.5 py-1.5 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
          role="status"
        >
          <AlertTriangle size={12} className="shrink-0" aria-hidden />
          {t.wiki.activeTasksPollFailed}
        </p>
      )}
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

            {task.phase && (
              <div className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {wikiPhaseLabel(t.wiki, task.phase)}
              </div>
            )}

            {task.detail && (
              <p className="mt-0.5 text-xs text-sky-600 dark:text-sky-400">{task.detail}</p>
            )}

            {/* Pipeline visualization */}
            <div className="mt-1.5">
              <button
                type="button"
                className="flex items-center gap-1 text-[10px] text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
                onClick={() =>
                  setExpandedPipeline((prev) => ({
                    ...prev,
                    [task.task_id]: !prev[task.task_id],
                  }))
                }
                aria-expanded={!!expandedPipeline[task.task_id]}
              >
                {expandedPipeline[task.task_id] ? (
                  <ChevronDown size={12} />
                ) : (
                  <ChevronRight size={12} />
                )}
                {t.wiki.pipelineVisualization}
              </button>
              <div className="mt-1">
                <WikiPipelineVisualization
                  nodeStatuses={task.node_statuses}
                  currentPhase={task.phase}
                  compact={!expandedPipeline[task.task_id]}
                />
              </div>
            </div>

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
