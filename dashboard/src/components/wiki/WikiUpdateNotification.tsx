import { RefreshCw, X } from "lucide-react";

interface WikiUpdateNotificationProps {
  pagePath: string;
  onRefresh: () => void;
  onDismiss: () => void;
}

export default function WikiUpdateNotification({
  pagePath,
  onRefresh,
  onDismiss,
}: WikiUpdateNotificationProps) {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm text-sky-800 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300">
      <RefreshCw size={16} className="shrink-0" />
      <span className="flex-1">
        Page <span className="font-medium">{pagePath.split("/").pop()}</span> has been updated.
      </span>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:text-sky-300 dark:hover:bg-sky-900"
      >
        Refresh
      </button>
      <button
        type="button"
        onClick={onDismiss}
        className="rounded p-1 text-sky-400 hover:text-sky-700 dark:hover:text-sky-200"
      >
        <X size={14} />
      </button>
    </div>
  );
}
