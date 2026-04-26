import { RefreshCw, X } from "lucide-react";
import { useI18n } from "../../i18n/context";

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
  const { t } = useI18n();
  const pageName = pagePath.split("/").pop() ?? pagePath;
  return (
    <div className="flex items-center gap-3 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2.5 text-sm text-sky-800 dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-300">
      <RefreshCw size={16} className="shrink-0" />
      <span className="flex-1">
        {(() => {
          const parts = t.wiki.notificationUpdated.split("{pageName}");
          if (parts.length === 1) return parts[0];
          return (
            <>
              {parts[0]}
              <span className="font-medium">{pageName}</span>
              {parts.slice(1).join(pageName)}
            </>
          );
        })()}
      </span>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100 dark:text-sky-300 dark:hover:bg-sky-900"
      >
        {t.wiki.notificationRefresh}
      </button>
      <button
        type="button"
        onClick={onDismiss}
        aria-label={t.wiki.notificationDismiss}
        className="rounded p-1 text-sky-400 hover:text-sky-700 dark:hover:text-sky-200"
      >
        <X size={14} />
      </button>
    </div>
  );
}
