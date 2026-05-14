import { useState, useEffect, useRef, useMemo } from "react";
import FocusTrap from "../components/FocusTrap";
import {
  Database,
  Loader2,
  CheckCircle2,
  XCircle,
  Clock,
  ArrowRight,
  CloudUpload,
  X,
  Building2,
} from "lucide-react";
import {
  useEnrich,
  useIndex,
  useIndexFiles,
  useIndexTask,
  useIndexTasks,
  useRepositories,
} from "../api/hooks";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { useToast } from "../components/Toast";
import JsonView from "../components/JsonView";
import type { IndexTask } from "../api/types";
import { useBusiness } from "../contexts/BusinessContext";
import { useBusinessRepositories } from "../hooks/useBusinessRepositories";

const UPLOAD_EXT = [".java", ".py", ".go", ".js", ".ts", ".tsx", ".md", ".txt"] as const;

function isUploadableFileName(name: string): boolean {
  const n = name.toLowerCase();
  return UPLOAD_EXT.some((ext) => n.endsWith(ext));
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result ?? ""));
    fr.onerror = () => reject(fr.error ?? new Error("read failed"));
    fr.readAsText(file);
  });
}

function phaseLabel(phase: string, t: Record<string, string>): string {
  const map: Record<string, string> = {
    scanning: t.phaseScan,
    indexing_code: t.phaseCode,
    indexing_docs: t.phaseDocs,
    indexing_and_enriching: t.phaseIndexingEnriching,
    enriching: t.phaseEnriching,
    embedding: t.phaseEmbedding,
    resolving_references: t.phaseRefs,
    completed: t.phaseComplete,
  };
  return map[phase] || phase;
}

function enrichmentModeLabel(
  backend: string | undefined,
  t: Record<string, string>,
): string {
  if (backend === "gateway") return t.enrichmentGateway;
  if (backend === "direct") return t.enrichmentDirect;
  return t.enrichmentDisabled;
}

function statusBadge(status: string, t: Record<string, string>) {
  const config: Record<string, { icon: typeof Clock; color: string; label: string }> = {
    pending: {
      icon: Clock,
      color:
        "text-gray-500 bg-gray-100 dark:bg-gray-800 dark:text-gray-400",
      label: t.taskPending,
    },
    running: {
      icon: Loader2,
      color:
        "text-sky-600 bg-sky-50 dark:bg-sky-950 dark:text-sky-400",
      label: t.taskRunning,
    },
    completed: {
      icon: CheckCircle2,
      color:
        "text-emerald-600 bg-emerald-50 dark:bg-emerald-950 dark:text-emerald-400",
      label: t.taskCompleted,
    },
    failed: {
      icon: XCircle,
      color:
        "text-red-600 bg-red-50 dark:bg-red-950 dark:text-red-400",
      label: t.taskFailed,
    },
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

export default function Indexing() {
  const [mode, setMode] = useState<"full" | "incremental">("full");
  const [directory, setDirectory] = useState("");
  const [repository, setRepository] = useState("");
  const [baseRef, setBaseRef] = useState("HEAD~1");
  const [headRef, setHeadRef] = useState("HEAD");
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [enrichModalOpen, setEnrichModalOpen] = useState(false);
  const [enrichRepository, setEnrichRepository] = useState("");
  const [enrichForce, setEnrichForce] = useState(false);

  const [queuedFiles, setQueuedFiles] = useState<{ id: string; file: File }[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  type UploadPhase = "idle" | "reading" | "sending" | "success" | "error";
  const [uploadPhase, setUploadPhase] = useState<UploadPhase>("idle");
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const [readProgress, setReadProgress] = useState({ done: 0, total: 0 });

  const { t } = useI18n();
  const mutation = useIndex();
  const enrichMutation = useEnrich();
  const indexFilesMutation = useIndexFiles();
  const reposQuery = useRepositories();
  const { currentBusiness, setCurrentBusiness, businesses, isLoading: businessesLoading, isBound } =
    useBusiness();
  const currentBizName =
    businesses.find((b) => b.id === currentBusiness)?.name || currentBusiness;
  const boundReposQuery = useBusinessRepositories(currentBusiness);
  const filteredRepositories = useMemo(() => {
    if (!boundReposQuery.isFetched) return [];
    const all = reposQuery.data?.repositories ?? [];
    const bound = boundReposQuery.data?.repositories ?? [];
    const set = new Set(bound);
    if (currentBusiness === "default" && set.size === 0) {
      return all;
    }
    return all.filter((r) => set.has(r.repository));
  }, [
    reposQuery.data?.repositories,
    boundReposQuery.data?.repositories,
    boundReposQuery.isFetched,
    currentBusiness,
  ]);
  const noBusinessAvailable = !businessesLoading && businesses.length === 0;
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
      const isEnrich = activeTask.data.mode === "enrich";
      toast("success", isEnrich ? t.indexing.enrichComplete : t.indexing.indexingComplete);
    } else if (status === "failed") {
      setToastedTaskId(task_id);
      toast("error", activeTask.data.error || t.indexing.indexingFailed);
    }
  }, [activeTask.data?.status, activeTask.data?.task_id]);

  function openEnrichModal() {
    const list = filteredRepositories;
    const fromIndex = repository.trim();
    if (fromIndex && list.some((r) => r.repository === fromIndex)) {
      setEnrichRepository(fromIndex);
    } else if (fromIndex) {
      setEnrichRepository(fromIndex);
    } else if (list.length > 0) {
      setEnrichRepository(list[0].repository);
    } else {
      setEnrichRepository("");
    }
    setEnrichForce(false);
    setEnrichModalOpen(true);
  }

  async function handleEnrichSubmit(e: React.FormEvent) {
    e.preventDefault();
    const name = enrichRepository.trim();
    if (!name) {
      toast("error", t.indexing.enrichRepositoryRequired);
      return;
    }
    try {
      const res = await enrichMutation.mutateAsync({
        repository: name,
        force: enrichForce,
      });
      if (res.task_id) {
        setActiveTaskId(res.task_id);
        setToastedTaskId(null);
        toast("success", `${t.indexing.taskId}: ${res.task_id}`);
      }
      setEnrichModalOpen(false);
    } catch (err) {
      toast("error", getErrorMessage(err, t.common.unexpectedError) || t.indexing.indexingFailed);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!directory.trim()) {
      toast("error", t.indexing.directoryRequired);
      return;
    }

    const val = directory.trim();
    const isGitUrl =
      val.startsWith("http://") ||
      val.startsWith("https://") ||
      val.startsWith("git@") ||
      val.startsWith("ssh://") ||
      val.endsWith(".git");

    const body: Record<string, unknown> = {
      business_id: currentBusiness,
      mode,
    };
    if (isGitUrl) {
      body.git_url = val;
    } else {
      body.directory = val;
    }
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
      toast("error", getErrorMessage(err, t.common.unexpectedError) || t.indexing.indexingFailed);
    }
  }

  function addFilesFromList(list: FileList | File[]) {
    const arr = Array.from(list);
    let skipped = 0;
    const next: { id: string; file: File }[] = [];
    for (const f of arr) {
      if (!isUploadableFileName(f.name)) {
        skipped++;
        continue;
      }
      next.push({
        id: `${f.name}-${f.size}-${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file: f,
      });
    }
    if (skipped > 0) {
      toast("error", `${t.indexing.uploadInvalidType} (${skipped})`);
    }
    if (next.length > 0) {
      setQueuedFiles((q) => [...q, ...next]);
      setUploadPhase("idle");
      setUploadMessage(null);
    }
  }

  async function handleUploadSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (queuedFiles.length === 0) {
      toast("error", t.indexing.uploadNoFiles);
      return;
    }
    setUploadPhase("reading");
    setUploadMessage(null);
    setReadProgress({ done: 0, total: queuedFiles.length });
    const filesPayload: { path: string; content: string }[] = [];
    try {
      let done = 0;
      for (const q of queuedFiles) {
        const content = await readFileAsText(q.file);
        filesPayload.push({ path: q.file.name, content });
        done++;
        setReadProgress({ done, total: queuedFiles.length });
      }
      setUploadPhase("sending");
      const res = await indexFilesMutation.mutateAsync({
        files: filesPayload,
        repository: "uploaded",
      });
      setQueuedFiles([]);
      setUploadPhase("success");
      setUploadMessage(t.indexing.uploadSuccess);
      if (res.task_id) {
        setActiveTaskId(res.task_id);
        setToastedTaskId(null);
        toast("success", `${t.indexing.uploadTaskStarted}: ${res.task_id}`);
      } else {
        toast("success", t.indexing.uploadSuccess);
      }
    } catch (err) {
      const msg = getErrorMessage(err, t.common.unexpectedError) || t.indexing.uploadError;
      setUploadPhase("error");
      setUploadMessage(msg);
      toast("error", msg);
    }
  }

  function removeQueued(id: string) {
    setQueuedFiles((q) => q.filter((x) => x.id !== id));
  }

  const inputClass =
    "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600";

  return (
    <div className="space-y-6">
      <h2 className="flex items-center gap-2 text-lg font-semibold text-gray-900 dark:text-gray-100">
        <Database size={20} /> {t.indexing.title}
      </h2>

      <form
        onSubmit={handleSubmit}
        className="space-y-4 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900"
      >
        {isBound ? (
          <div className="flex items-center gap-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-600 dark:border-gray-600 dark:bg-gray-800/80 dark:text-gray-300">
            <Building2 size={16} aria-hidden className="shrink-0 text-gray-500 dark:text-gray-400" />
            <span>
              <span className="text-gray-500 dark:text-gray-400">{t.indexing.businessLabel}: </span>
              <span className="font-medium text-gray-800 dark:text-gray-100">{currentBizName}</span>
            </span>
          </div>
        ) : businessesLoading ? (
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <Loader2 size={16} className="animate-spin" aria-hidden />
            {t.common.loading}
          </div>
        ) : businesses.length > 0 ? (
          <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
            {t.indexing.businessLabel}
            <select
              value={currentBusiness}
              onChange={(e) => setCurrentBusiness(e.target.value)}
              className={`mt-1 ${inputClass}`}
            >
              {businesses.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <p className="text-sm text-amber-800 dark:text-amber-200" role="status">
            {t.indexing.createBusinessFirst}
          </p>
        )}

        <div className="space-y-1">
          <div className="flex gap-4">
            {(["full", "incremental"] as const).map((m) => (
              <label key={m} className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
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
          <p className="text-xs text-gray-400 dark:text-gray-500">
            {mode === "full" ? t.indexing.fullDesc : t.indexing.incrementalDesc}
          </p>
        </div>

        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
          {t.indexing.directoryPath}
          <input
            type="text"
            value={directory}
            onChange={(e) => setDirectory(e.target.value)}
            placeholder={t.indexing.directoryPlaceholder}
            className={`mt-1 ${inputClass}`}
          />
        </label>

        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
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
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
              {t.indexing.baseRef}
              <input
                type="text"
                value={baseRef}
                onChange={(e) => setBaseRef(e.target.value)}
                className={`mt-1 ${inputClass}`}
              />
            </label>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
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
          disabled={mutation.isPending || noBusinessAvailable}
          title={noBusinessAvailable ? t.indexing.createBusinessFirst : undefined}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
        >
          {mutation.isPending && <Loader2 size={16} className="animate-spin" />}
          {t.indexing.startIndexing}
        </button>

        <div className="flex flex-col gap-3 border-t border-gray-100 pt-4 dark:border-gray-700 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-gray-500 dark:text-gray-400">{t.indexing.enrichDesc}</p>
          <button
            type="button"
            onClick={openEnrichModal}
            disabled={enrichMutation.isPending || noBusinessAvailable}
            title={noBusinessAvailable ? t.indexing.createBusinessFirst : undefined}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-lg border border-sky-600 bg-white px-5 py-2.5 text-sm font-medium text-sky-700 transition-colors hover:bg-sky-50 disabled:opacity-50 dark:border-sky-500 dark:bg-gray-900 dark:text-sky-400 dark:hover:bg-sky-950"
          >
            {enrichMutation.isPending && <Loader2 size={16} className="animate-spin" />}
            {t.indexing.enrichTitle}
          </button>
        </div>
      </form>

      <form
        onSubmit={handleUploadSubmit}
        className="space-y-4 rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900"
      >
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {t.indexing.uploadSectionTitle}
        </h3>

        <input
          ref={fileInputRef}
          id="kb-file-upload-input"
          type="file"
          multiple
          accept=".java,.py,.go,.js,.ts,.tsx,.md,.txt"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => {
            if (e.target.files?.length) addFilesFromList(e.target.files);
            e.target.value = "";
          }}
        />

        <label
          htmlFor="kb-file-upload-input"
          onDragOver={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setDragActive(true);
          }}
          onDragLeave={(e) => {
            e.preventDefault();
            setDragActive(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            e.stopPropagation();
            setDragActive(false);
            if (e.dataTransfer.files?.length) addFilesFromList(e.dataTransfer.files);
          }}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors sm:gap-3 ${
            dragActive
              ? "border-sky-400 bg-sky-50 dark:border-sky-500 dark:bg-sky-950/40"
              : "border-gray-300 bg-gray-50/60 dark:border-gray-600 dark:bg-gray-800/40"
          }`}
        >
          <CloudUpload
            className="text-gray-400 dark:text-gray-500"
            size={40}
            strokeWidth={1.25}
            aria-hidden
          />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {t.indexing.uploadDropHint}
          </span>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {t.indexing.uploadAcceptedHint}
          </span>
          <span className="sr-only">{t.indexing.uploadBrowse}</span>
        </label>

        {queuedFiles.length > 0 && (
          <ul className="divide-y divide-gray-100 overflow-hidden rounded-lg border border-gray-200 dark:divide-gray-700 dark:border-gray-600">
            {queuedFiles.map((q) => (
              <li
                key={q.id}
                className="flex items-center justify-between gap-3 bg-white px-3 py-2 dark:bg-gray-900"
              >
                <span className="min-w-0 truncate font-mono text-xs text-gray-800 dark:text-gray-200">
                  {q.file.name}
                </span>
                <button
                  type="button"
                  onClick={() => removeQueued(q.id)}
                  className="shrink-0 rounded p-1 text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-700 dark:hover:bg-gray-800 dark:hover:text-gray-200"
                  aria-label={t.indexing.uploadRemoveFile}
                >
                  <X size={16} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {(uploadPhase === "reading" || uploadPhase === "sending") && (
          <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
            <Loader2 size={16} className="shrink-0 animate-spin" />
            <span>
              {uploadPhase === "reading"
                ? `${t.indexing.uploadReading} (${readProgress.done}/${readProgress.total})`
                : t.indexing.uploadSending}
            </span>
          </div>
        )}

        {uploadPhase === "success" && uploadMessage && (
          <div className="flex items-center gap-2 text-sm text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 size={16} aria-hidden />
            {uploadMessage}
          </div>
        )}

        {uploadPhase === "error" && uploadMessage && (
          <div className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
            <XCircle size={16} aria-hidden />
            {uploadMessage}
          </div>
        )}

        <button
          type="submit"
          disabled={
            queuedFiles.length === 0 ||
            uploadPhase === "reading" ||
            uploadPhase === "sending" ||
            indexFilesMutation.isPending ||
            noBusinessAvailable
          }
          title={noBusinessAvailable ? t.indexing.createBusinessFirst : undefined}
          className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
        >
          {(uploadPhase === "reading" ||
            uploadPhase === "sending" ||
            indexFilesMutation.isPending) && (
            <Loader2 size={16} className="animate-spin" />
          )}
          {t.indexing.uploadAndIndex}
        </button>
      </form>

      {enrichModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 dark:bg-black/60"
          role="dialog"
          aria-modal="true"
          aria-labelledby="enrich-modal-title"
        >
          <FocusTrap onEscape={() => setEnrichModalOpen(false)}>
          <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-lg dark:border-gray-600 dark:bg-gray-900">
            <h3 id="enrich-modal-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
              {t.indexing.enrichTitle}
            </h3>
            <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{t.indexing.enrichDesc}</p>
            <form onSubmit={handleEnrichSubmit} className="mt-4 space-y-4">
              <div className="space-y-1">
                <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
                  {t.indexing.enrichRepository}
                </label>
                {(filteredRepositories.length ?? 0) > 0 ? (
                  <select
                    value={enrichRepository}
                    onChange={(e) => setEnrichRepository(e.target.value)}
                    className={inputClass}
                  >
                    <option value="">{t.indexing.enrichRepository}</option>
                    {filteredRepositories.map((r) => (
                      <option key={r.repository} value={r.repository}>
                        {r.repository}
                      </option>
                    ))}
                  </select>
                ) : (
                  <>
                    <p className="text-xs text-amber-700 dark:text-amber-400">{t.indexing.enrichManualHint}</p>
                    <input
                      type="text"
                      value={enrichRepository}
                      onChange={(e) => setEnrichRepository(e.target.value)}
                      placeholder={t.indexing.repoPlaceholder}
                      className={inputClass}
                    />
                  </>
                )}
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
                <input
                  type="checkbox"
                  checked={enrichForce}
                  onChange={(e) => setEnrichForce(e.target.checked)}
                  className="accent-sky-500"
                />
                {t.indexing.enrichForce}
              </label>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEnrichModalOpen(false)}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
                >
                  {t.businesses.cancel}
                </button>
                <button
                  type="submit"
                  disabled={enrichMutation.isPending}
                  className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
                >
                  {enrichMutation.isPending && <Loader2 size={16} className="animate-spin" />}
                  {t.indexing.enrichTrigger}
                </button>
              </div>
            </form>
          </div>
          </FocusTrap>
        </div>
      )}

      {activeTask.data && (
        <TaskProgress task={activeTask.data} />
      )}

      {/* Recent Tasks */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">
          {t.indexing.recentTasks}
        </h3>
        {tasksList.data?.tasks && tasksList.data.tasks.length > 0 ? (
          <div className="space-y-2">
            {tasksList.data.tasks
              .filter((task) => task.task_id !== activeTaskId)
              .slice(0, 10)
              .map((task) => (
                <div
                  key={task.task_id}
                  className="flex items-center justify-between rounded-lg border border-gray-100 bg-white px-4 py-3 text-sm dark:border-gray-700 dark:bg-gray-900"
                >
                  <div className="flex items-center gap-3">
                    {statusBadge(task.status, t.indexing)}
                    <span className="text-gray-700 dark:text-gray-200">{task.mode} • {task.directory}</span>
                    {task.repository && (
                      <span className="text-gray-400 dark:text-gray-500">({task.repository})</span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-xs text-gray-400 dark:text-gray-500">
                    <span>{new Date(task.created_at).toLocaleString()}</span>
                    <button
                      type="button"
                      onClick={() => setActiveTaskId(task.task_id)}
                      className="text-sky-500 hover:text-sky-600 dark:text-sky-400 dark:hover:text-sky-300"
                    >
                      {t.indexing.viewDetails}
                    </button>
                  </div>
                </div>
              ))}
          </div>
        ) : (
          <p className="text-sm text-gray-400 dark:text-gray-500">{t.indexing.noTasks}</p>
        )}
      </div>
    </div>
  );
}
