import { useId, useState } from "react";
import FocusTrap from "../../FocusTrap";
import { useI18n } from "../../../i18n/context";

interface CreateSubdomainDialogProps {
  onConfirm: (title: string, description: string) => void;
  onCancel: () => void;
}

export default function CreateSubdomainDialog({ onConfirm, onCancel }: CreateSubdomainDialogProps) {
  const { t } = useI18n();
  const titleId = useId();
  const titleInputId = useId();
  const descriptionInputId = useId();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={onCancel}
    >
      <FocusTrap onEscape={onCancel}>
        <div
          className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-xl dark:border-gray-700 dark:bg-gray-900"
          onClick={(e) => e.stopPropagation()}
        >
          <h3 id={titleId} className="mb-4 text-lg font-semibold text-gray-900 dark:text-white">
            {t.wiki.domain_management.createTitle}
          </h3>
        <label htmlFor={titleInputId} className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">{t.wiki.domain_management.renameLabel}</label>
        <input
          id={titleInputId}
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mb-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          autoFocus
        />
        <label htmlFor={descriptionInputId} className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300">{t.wiki.domain_management.descriptionLabel}</label>
        <textarea
          id={descriptionInputId}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-800 dark:text-white"
          rows={3}
        />
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
            disabled={!title.trim()}
            className="rounded-lg bg-sky-600 px-4 py-2 text-sm text-white hover:bg-sky-700 disabled:opacity-50"
          >
            {t.wiki.domain_management.confirm}
          </button>
        </div>
        </div>
      </FocusTrap>
    </div>
  );
}
