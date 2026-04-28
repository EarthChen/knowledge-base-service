import { Trash2 } from "lucide-react";
import type { WikiAnnotation } from "../../hooks/wikiTypes";
import { useI18n } from "../../i18n/context";

interface WikiAnnotationSidebarProps {
  annotations: WikiAnnotation[];
  onDelete: (id: string) => void;
  isDeleting: boolean;
}

export default function WikiAnnotationSidebar({
  annotations,
  onDelete,
  isDeleting,
}: WikiAnnotationSidebarProps) {
  const { t } = useI18n();
  if (!Array.isArray(annotations) || annotations.length === 0) {
    return (
      <p className="px-4 py-6 text-center text-xs text-gray-500 dark:text-gray-400">
        {t.wiki.annotationsEmpty}
      </p>
    );
  }

  return (
    <div className="space-y-2 px-3 py-3">
      {annotations.map((a) => (
        <div
          key={a.annotation_id}
          className="rounded-lg border border-gray-100 bg-gray-50/50 p-3 dark:border-gray-800 dark:bg-gray-800/30"
        >
          <p className="text-sm text-gray-800 dark:text-gray-200">{a.comment}</p>
          <div className="mt-2 flex items-center justify-between text-[11px] text-gray-500 dark:text-gray-400">
            <span>
              {a.author} &middot; {new Date(a.created_at).toLocaleDateString()}
            </span>
            <button
              type="button"
              onClick={() => onDelete(a.annotation_id)}
              disabled={isDeleting}
              aria-label={t.wiki.annotationDelete}
              className="rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 dark:hover:bg-red-950 dark:hover:text-red-400"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
