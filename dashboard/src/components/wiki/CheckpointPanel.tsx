import { useMemo } from "react";
import { Database, Loader2, Trash2 } from "lucide-react";
import { useI18n } from "../../i18n/context";
import { getErrorMessage } from "../../utils/errorUtils";
import { useCheckpoint, useDeleteCheckpoint } from "../../hooks/useCheckpoint";

type Props = {
  businessId: string;
};

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v < 10 && i > 0 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

function formatModified(ts: number): string {
  if (!ts) return "—";
  const ms = ts > 10_000_000_000 ? ts : ts * 1000;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString();
}

export default function CheckpointPanel({ businessId }: Props) {
  const { t } = useI18n();
  const checkpointQuery = useCheckpoint(businessId);
  const deleteCheckpoint = useDeleteCheckpoint(businessId);

  const cp = checkpointQuery.data;
  const exists = !!cp;

  const shellClass = useMemo(
    () =>
      exists
        ? "border-emerald-200 bg-emerald-50/80 dark:border-emerald-900/40 dark:bg-emerald-950/25"
        : "border-gray-200 bg-gray-50/60 dark:border-gray-700 dark:bg-gray-900/40",
    [exists],
  );

  const handleDelete = () => {
    const ok = window.confirm(
      "Delete the wiki checkpoint for this businessID? You may need a full regeneration to recover.",
    );
    if (!ok) return;
    deleteCheckpoint.mutate();
  };

  return (
    <div className={`rounded-xl border p-4 ${shellClass}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <Database
            size={18}
            className={exists ? "text-emerald-700 dark:text-emerald-400" : "text-gray-400 dark:text-gray-500"}
            aria-hidden
          />
          <div>
            <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Checkpoint</h3>
            <p className="text-xs text-gray-600 dark:text-gray-400">
              {checkpointQuery.isLoading
                ? t.common.loading
                : exists
                  ? "A checkpoint file exists for this business."
                  : "No checkpoint found."}
            </p>
          </div>
        </div>
        <div
          className={`rounded-full px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
            exists
              ? "bg-emerald-600/15 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300"
              : "bg-gray-200 text-gray-600 dark:bg-gray-800 dark:text-gray-400"
          }`}
          role="status"
        >
          {exists ? "Present" : "None"}
        </div>
      </div>

      {checkpointQuery.isError && (
        <p className="mt-3 text-xs text-red-600 dark:text-red-400" role="alert">
          {getErrorMessage(checkpointQuery.error, t.common.unexpectedError)}
        </p>
      )}

      {exists && cp && (
        <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-2">
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Last modified</dt>
            <dd className="font-medium text-gray-900 dark:text-gray-100">{formatModified(cp.last_modified)}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Size</dt>
            <dd className="font-medium text-gray-900 dark:text-gray-100">{formatBytes(cp.size_bytes)}</dd>
          </div>
          <div className="sm:col-span-2">
            <dt className="text-gray-500 dark:text-gray-400">Path</dt>
            <dd className="break-all font-mono text-[11px] text-gray-800 dark:text-gray-200">{cp.db_path}</dd>
          </div>
        </dl>
      )}

      {deleteCheckpoint.isError && (
        <p className="mt-3 text-xs text-red-600 dark:text-red-400" role="alert">
          {getErrorMessage(deleteCheckpoint.error, t.common.unexpectedError)}
        </p>
      )}

      <div className="mt-4">
        <button
          type="button"
          onClick={handleDelete}
          disabled={!exists || deleteCheckpoint.isPending || checkpointQuery.isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-red-900/40 dark:bg-transparent dark:text-red-400 dark:hover:bg-red-950/30"
        >
          {deleteCheckpoint.isPending ? (
            <Loader2 size={14} className="animate-spin" aria-hidden />
          ) : (
            <Trash2 size={14} aria-hidden />
          )}
          Delete checkpoint
        </button>
      </div>
    </div>
  );
}
