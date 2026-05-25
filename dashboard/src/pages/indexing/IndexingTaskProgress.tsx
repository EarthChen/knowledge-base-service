import { ArrowRight } from "lucide-react";
import { useI18n } from "../../i18n/context";
import JsonView from "../../components/JsonView";
import type { IndexTask } from "../../api/types";
import { enrichmentModeLabel, phaseLabel, statusBadge } from "./indexingUtils";

export function IndexingTaskProgress({ task }: { task: IndexTask }) {
  const { t } = useI18n();
  const ti = t.indexing;
  const { progress } = task;
  const pct = progress.total_files > 0
    ? Math.round((progress.processed_files / progress.total_files) * 100)
    : 0;
  const enrichBackend = progress.enrichment_backend;
  const showEnrichmentRow =
    !!enrichBackend ||
    (progress.enriched_count != null && progress.enriched_count > 0) ||
    progress.phase === "indexing_and_enriching" ||
    progress.phase === "enriching";

  return (
    <div className="space-y-3 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {statusBadge(task.status, ti)}
          <span className="text-xs text-gray-500 dark:text-gray-400">{ti.taskId}: {task.task_id}</span>
        </div>
        <span className="text-xs text-gray-400 dark:text-gray-500">
          {task.mode} • {task.directory}
        </span>
      </div>

      {showEnrichmentRow && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-100 bg-amber-50/80 px-3 py-2 text-xs text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200">
          <span className="font-medium">{ti.enrichmentMode}:</span>
          <span>{enrichmentModeLabel(enrichBackend, ti)}</span>
          {(progress.enriched_count != null && progress.enriched_count > 0) && (
            <span className="text-amber-800 dark:text-amber-300">
              · {ti.entitiesEnriched}: <strong>{progress.enriched_count}</strong>
            </span>
          )}
        </div>
      )}

      {task.status === "running" && (
        <>
          <div className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
            <ArrowRight size={14} className="text-sky-500" />
            <span className="font-medium">{phaseLabel(progress.phase, ti)}</span>
            {progress.total_files > 0 && (
              <span className="text-gray-400 dark:text-gray-500">
                ({progress.processed_files}/{progress.total_files} {ti.files})
              </span>
            )}
          </div>

          {progress.total_files > 0 && (
            <div className="relative h-2 w-full overflow-hidden rounded-full bg-gray-100 dark:bg-gray-800">
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-sky-500 transition-all duration-300 dark:bg-sky-400"
                style={{ width: `${pct}%` }}
              />
            </div>
          )}

          {progress.current_file && (
            <p className="truncate text-xs text-gray-400 dark:text-gray-500">
              {ti.currentFile}: {progress.current_file}
            </p>
          )}

          {Object.keys(progress.stats).length > 0 && (
            <div className="flex flex-wrap gap-3 text-xs text-gray-500 dark:text-gray-400">
              {Object.entries(progress.stats).map(([k, v]) => (
                <span key={k}>{k}: <strong>{v}</strong></span>
              ))}
            </div>
          )}
        </>
      )}

      {task.status === "completed" && task.result && (
        <div className="space-y-3">
          {typeof task.result.stats === "object" &&
            task.result.stats !== null &&
            "enriched" in (task.result.stats as Record<string, unknown>) && (
              <p className="text-sm text-gray-700 dark:text-gray-200">
                {ti.entitiesEnriched}:{" "}
                <strong>
                  {String((task.result.stats as Record<string, unknown>).enriched)}
                </strong>
              </p>
            )}
          <JsonView data={task.result} />
        </div>
      )}

      {task.status === "failed" && task.error && (
        <p className="text-sm text-red-600 dark:text-red-400">{task.error}</p>
      )}
    </div>
  );
}
