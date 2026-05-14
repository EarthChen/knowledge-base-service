import { useState } from "react";
import { useI18n } from "../../../i18n/context";

interface RenameDialogProps {
  currentTitle: string;
  currentDescription?: string;
  /** When true, shows a generic failure message (mutation error from caller). */
  isError?: boolean;
  /** Disables confirm while mutation is in flight. */
  isPending?: boolean;
  onConfirm: (title: string, description: string) => void;
  onCancel: () => void;
}

export default function RenameDialog({
  currentTitle,
  currentDescription,
  isError,
  isPending,
  onConfirm,
  onCancel,
}: RenameDialogProps) {
  const { t } = useI18n();
  const [title, setTitle] = useState(currentTitle);
  const [description, setDescription] = useState(currentDescription ?? "");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onCancel}>
      <div
        className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-900"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">{t.wiki.domain_management.renameTitle}</h3>
        <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">{t.wiki.domain_management.renameLabel}</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          autoFocus
        />
        <label className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">{t.wiki.domain_management.descriptionLabel}</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          rows={3}
        />
        {isError ? (
          <p className="mb-3 text-sm text-red-600 dark:text-red-400" role="alert">
            {t.wiki.domain_management.operation_failed}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            {t.wiki.domain_management.cancel}
          </button>
          <button
            type="button"
            onClick={() => onConfirm(title, description)}
            disabled={!title.trim() || isPending}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {t.wiki.domain_management.confirm}
          </button>
        </div>
      </div>
    </div>
  );
}
