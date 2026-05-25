import { useState, useEffect, useMemo } from "react";
import {
  Database,
  Loader2,
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
import { useBusiness } from "../contexts/BusinessContext";
import { useBusinessRepositories } from "../hooks/useBusinessRepositories";
import { IndexingEnrichModal } from "./indexing/IndexingEnrichModal";
import { IndexingTaskList } from "./indexing/IndexingTaskList";
import { IndexingTaskProgress } from "./indexing/IndexingTaskProgress";
import { IndexingUploadPanel, type UploadPhase } from "./indexing/IndexingUploadPanel";
import { INPUT_CLASS, isUploadableFileName, readFileAsText } from "./indexing/indexingUtils";

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
      (task) => task.status === "running" || task.status === "pending",
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
              className={`mt-1 ${INPUT_CLASS}`}
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
            className={`mt-1 ${INPUT_CLASS}`}
          />
        </label>

        <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
          {t.indexing.repoName}
          <input
            type="text"
            value={repository}
            onChange={(e) => setRepository(e.target.value)}
            placeholder={t.indexing.repoPlaceholder}
            className={`mt-1 ${INPUT_CLASS}`}
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
                className={`mt-1 ${INPUT_CLASS}`}
              />
            </label>
            <label className="block text-xs font-medium text-gray-500 dark:text-gray-400">
              {t.indexing.headRef}
              <input
                type="text"
                value={headRef}
                onChange={(e) => setHeadRef(e.target.value)}
                className={`mt-1 ${INPUT_CLASS}`}
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

      <IndexingUploadPanel
        queuedFiles={queuedFiles}
        dragActive={dragActive}
        uploadPhase={uploadPhase}
        uploadMessage={uploadMessage}
        readProgress={readProgress}
        noBusinessAvailable={noBusinessAvailable}
        isPending={indexFilesMutation.isPending}
        onAddFiles={addFilesFromList}
        onRemoveQueued={(id) => setQueuedFiles((q) => q.filter((x) => x.id !== id))}
        onSubmit={handleUploadSubmit}
        onDragActiveChange={setDragActive}
      />

      <IndexingEnrichModal
        open={enrichModalOpen}
        repositories={filteredRepositories}
        enrichRepository={enrichRepository}
        enrichForce={enrichForce}
        isPending={enrichMutation.isPending}
        onRepositoryChange={setEnrichRepository}
        onForceChange={setEnrichForce}
        onSubmit={handleEnrichSubmit}
        onClose={() => setEnrichModalOpen(false)}
      />

      {activeTask.data && <IndexingTaskProgress task={activeTask.data} />}

      <IndexingTaskList
        tasks={tasksList.data?.tasks ?? []}
        activeTaskId={activeTaskId}
        onViewDetails={setActiveTaskId}
      />
    </div>
  );
}
