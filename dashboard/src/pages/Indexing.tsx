import { useState, useEffect } from "react";
import { Database, Loader2, CheckCircle2, XCircle, Clock, ArrowRight } from "lucide-react";
import { useIndex, useIndexTask, useIndexTasks } from "../api/hooks";
import { useI18n } from "../i18n/context";
import { useToast } from "../components/Toast";
import JsonView from "../components/JsonView";
import type { IndexTask } from "../api/types";

function phaseLabel(phase: string, t: Record<string, string>): string {
  const map: Record<string, string> = {
    scanning: t.phaseScan,
    indexing_code: t.phaseCode,
    indexing_docs: t.phaseDocs,
    resolving_references: t.phaseRefs,
    completed: t.phaseComplete,
  };
  return map[phase] || phase;
}

function statusBadge(status: string, t: Record<string, string>) {
  const config: Record<string, { icon: typeof Clock; color: string; label: string }> = {
    pending: { icon: Clock, color: "text-gray-500 bg-gray-100", label: t.taskPending },
    running: { icon: Loader2, color: "text-sky-600 bg-sky-50", label: t.taskRunning },
    completed: { icon: CheckCircle2, color: "text-emerald-600 bg-emerald-50", label: t.taskCompleted },
    failed: { icon: XCircle, color: "text-red-600 bg-red-50", label: t.taskFailed },
  };
  const c = config[status] || config.pending;
  const Icon = c.icon;
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${c.color}`}>
      <Icon size={12} className={status === "running" ? "animate-spin" : ""} />
      {c.label}
    </span>
  );
}

function TaskProgress({ task }: { task: IndexTask }) {
  const { t } = useI18n();
  const ti = t.indexing;
  const { progress } = task;
  const pct = progress.total_files > 0
    ? Math.round((progress.processed_files / progress.total_files) * 100)
    : 0;

  return (
    <div className="space-y-3 rounded-xl border border-gray-200 bg-white p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {statusBadge(task.status, ti)}
          <span className="text-xs text-gray-500">{ti.taskId}: {task.task_id}</span>
        </div>
        <span className="text-xs text-gray-400">
          {task.mode} • {task.directory}
        </span>
      </div>

      {task.status === "running" && (
        <>
          <div className="flex items-center gap-2 text-sm text-gray-700">
            <ArrowRight size={14} className="text-sky-500" />
            <span className="font-medium">{phaseLabel(progress.phase, ti)}</span>
            {progress.total_files > 0 && (
              <span className="text-gray-400">
                ({progress.processed_files}/{progress.total_files} {ti.files})
              </span>
            )}
          </div>

          {progress.total_files > 0 && (
            <div className="relative h-2 w-full overflow-hidden rounded-full bg-gray-100">
              <div
                className="absolute inset-y-0 left-0 rounded-full bg-sky-500 transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          )}

          {progress.current_file && (
            <p className="truncate text-xs text-gray-400">
              {ti.currentFile}: {progress.current_file}
            </p>
          )}

          {Object.keys(progress.stats).length > 0 && (
            <div className="flex flex-wrap gap-3 text-xs text-gray-500">
              {Object.entries(progress.stats).map(([k, v]) => (
                <span key={k}>{k}: <strong>{v}</strong></span>
              ))}
            </div>
          )}
        </>
      )}

      {task.status === "completed" && task.result && (
        <JsonView data={task.result} />
      )}

      {task.status === "failed" && task.error && (
        <p className="text-sm text-red-600">{task.error}</p>
      )}
    </div>
  );
}

export default function Indexing() {
  const [mode, setMode] = useState<"full" | "incremental">("full");
  const [directory, setDirectory] = useState("");
  const [repository, setRepository] = useState("");
  const [baseRef, setBaseRef] = useState("HEAD~1");
  const [headRef, setHeadRef] = useState("HEAD");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  const { t } = useI18n();
  const mutation = useIndex();
  const { toast } = useToast();
  const activeTask = useIndexTask(activeTaskId);
  const tasksList = useIndexTasks();

  const [toastedTaskId, setToastedTaskId] = useState<string | null>(null);

  useEffect(() => {
    if (activeTaskId) return;
    const running = tasksList.data?.tasks?.find(
      (t) => t.status === "running" || t.status === "pending",
    );
    if (running) {
      setActiveTaskId(running.task_id);
    }
  }, [tasksList.data?.tasks, activeTaskId]);

  useEffect(() => {
    if (!activeTask.data) return;
    const { task_id, status } = activeTask.data;
    if (toastedTaskId === task_id) return;
    if (status === "completed") {
      setToastedTaskId(task_id);
      toast("success", t.indexing.indexingComplete);
    } else if (status === "failed") {
      setToastedTaskId(task_id);
      toast("error", activeTask.data.error || t.indexing.indexingFailed);
    }
  }, [activeTask.data?.status, activeTask.data?.task_id]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!directory.trim()) {
      toast("error", t.indexing.directoryRequired);
      return;
    }

    const body: Record<string, unknown> = {
      directory: directory.trim(),
      mode,
    };
    if (mode === "incremental") {
      body.base_ref = baseRef;
      body.head_ref = headRef;
    }
    if (repository.trim()) body.repository = repository.trim();

    try {
      const res = await mutation.mutateAsync(body);
      if (res.task_id) {
        setActiveTaskId(res.task_id);
        toast("success", `${t.indexing.taskId}: ${res.task_id}`);
      }
    } catch (err) {
      toast("error", (err as Error).message || t.indexing.indexingFailed);
    }
  }

  const inputClass =
    "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300";

  const isRunning = activeTask.data?.status === "running" || activeTask.data?.status === "pending";

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900">
        <Database size={20} /> {t.indexing.title}
      </h2>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-gray-200 bg-white p-5"
      >
        <div className="space-y-1">
          <div className="flex gap-4">
            {(["full", "incremental"] as const).map((m) => (
              <label key={m} className="flex items-center gap-2 text-sm text-gray-700">
                <input
                  type="radio"
                  name="index-mode"
                  value={m}
                  checked={mode === m}
                  onChange={() => setMode(m)}
                  className="accent-sky-500"
                />
                {m === "full" ? t.indexing.full : t.indexing.incremental}
              </label>
            ))}
          </div>
          <p className="text-xs text-gray-400">
            {mode === "full" ? t.indexing.fullDesc : t.indexing.incrementalDesc}
          </p>
        </div>

        <label className="block text-xs font-medium text-gray-500">
          {t.indexing.directoryPath}
          <input
            type="text"
            value={directory}
            onChange={(e) => setDirectory(e.target.value)}
            placeholder={t.indexing.directoryPlaceholder}
            className={`mt-1 ${inputClass}`}
          />
        </label>

        <label className="block text-xs font-medium text-gray-500">
          {t.indexing.repoName}
          <input
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            placeholder={t.indexing.repoPlaceholder}
            className={`mt-1 ${inputClass}`}
          />
        </label>

        {mode === "incremental" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-gray-500">
              {t.indexing.baseRef}
              <input
                type="text"
                value={baseRef}
                onChange={(e) => setBaseRef(e.target.value)}
                className={`mt-1 ${inputClass}`}
              />
            </label>
            <label className="block text-xs font-medium text-gray-500">
              {t.indexing.headRef}
              <input
                type="text"
                value={headRef}
                onChange={(e) => setHeadRef(e.target.value)}
                className={`mt-1 ${inputClass}`}
              />
            </label>
          </div>
        )}

        <button
          type="submit"
          disabled={mutation.isPending || isRunning}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50"
        >
          {(mutation.isPending || isRunning) && <Loader2 size={16} className="animate-spin" />}
          {isRunning ? t.indexing.indexingInProgress : t.indexing.startIndexing}
        </button>
      </form>

      {activeTask.data && (
        <TaskProgress task={activeTask.data} />
      )}

      {/* Recent Tasks */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-700">{t.indexing.recentTasks}</h3>
        {tasksList.data?.tasks && tasksList.data.tasks.length > 0 ? (
          <div className="space-y-2">
            {tasksList.data.tasks
              .filter((task) => task.task_id !== activeTaskId)
              .slice(0, 10)
              .map((task) => (
                <div
                  key={task.task_id}
                  className="flex items-center justify-between rounded-lg border border-gray-100 bg-white px-4 py-3 text-sm"
                >
                  <div className="flex items-center gap-3">
                    {statusBadge(task.status, t.indexing)}
                    <span className="text-gray-700">{task.mode} • {task.directory}</span>
                    {task.repository && (
                      <span className="text-gray-400">({task.repository})</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-400">
                    <span>{new Date(task.created_at).toLocaleString()}</span>
                    <button
                      type="button"
                      onClick={() => setActiveTaskId(task.task_id)}
                      className="text-sky-500 hover:text-sky-600"
                    >
                      {t.indexing.viewDetails}
                    </button>
                  </div>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400">{t.indexing.noTasks}</p>
        )}
      </div>
    </div>
  );
}
