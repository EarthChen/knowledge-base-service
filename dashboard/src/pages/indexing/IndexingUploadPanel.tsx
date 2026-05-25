import { useRef } from "react";
import { CheckCircle2, CloudUpload, Loader2, X, XCircle } from "lucide-react";
import { useI18n } from "../../i18n/context";

export type UploadPhase = "idle" | "reading" | "sending" | "success" | "error";

interface QueuedFile {
  id: string;
  file: File;
}

interface Props {
  queuedFiles: QueuedFile[];
  dragActive: boolean;
  uploadPhase: UploadPhase;
  uploadMessage: string | null;
  readProgress: { done: number; total: number };
  noBusinessAvailable: boolean;
  isPending: boolean;
  onAddFiles: (files: FileList | File[]) => void;
  onRemoveQueued: (id: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onDragActiveChange: (active: boolean) => void;
}

export function IndexingUploadPanel({
  queuedFiles,
  dragActive,
  uploadPhase,
  uploadMessage,
  readProgress,
  noBusinessAvailable,
  isPending,
  onAddFiles,
  onRemoveQueued,
  onSubmit,
  onDragActiveChange,
}: Props) {
  const { t } = useI18n();
  const fileInputRef = useRef<HTMLInputElement>(null);

  return (
    <form
      onSubmit={onSubmit}
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
          if (e.target.files?.length) onAddFiles(e.target.files);
          e.target.value = "";
        }}
      />

      <label
        htmlFor="kb-file-upload-input"
        onDragOver={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDragActiveChange(true);
        }}
        onDragLeave={(e) => {
          e.preventDefault();
          onDragActiveChange(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onDragActiveChange(false);
          if (e.dataTransfer.files?.length) onAddFiles(e.dataTransfer.files);
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
                onClick={() => onRemoveQueued(q.id)}
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
          isPending ||
          noBusinessAvailable
        }
        title={noBusinessAvailable ? t.indexing.createBusinessFirst : undefined}
        className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
      >
        {(uploadPhase === "reading" || uploadPhase === "sending" || isPending) && (
          <Loader2 size={16} className="animate-spin" />
        )}
        {t.indexing.uploadAndIndex}
      </button>
    </form>
  );
}
