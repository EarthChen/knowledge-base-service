import { useId, useState } from "react";
import FocusTrap from "../../FocusTrap";
import { useI18n } from "../../../i18n/context";

interface DeleteDialogProps {
  domainTitle: string;
  onConfirm: (promoteChildren: boolean) => void;
  onCancel: () => void;
}

export default function DeleteDialog({ domainTitle, onConfirm, onCancel }: DeleteDialogProps) {
  const { t } = useI18n();
  const titleId = useId();
  const [promoteChildren, setPromoteChildren] = useState(true);

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
          <h3 id={titleId} className="mb-2 text-lg font-semibold text-gray-900 dark:text-white">
            {t.wiki.domain_management.deleteTitle}
          </h3>
        <p className="mb-4 text-sm text-gray-600 dark:text-gray-400">{t.wiki.domain_management.deleteConfirm}</p>
        <p className="mb-3 text-sm font-medium text-gray-800 dark:text-gray-200">{domainTitle}</p>
        <fieldset className="mb-4 space-y-2">
          <legend className="mb-2 text-sm font-medium text-gray-700 dark:text-gray-300">
            {t.wiki.domain_management.deleteOptions}
          </legend>
          <label className="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
            <input type="radio" name="delete-option" checked={promoteChildren} onChange={() => setPromoteChildren(true)} className="accent-sky-600" />
            {t.wiki.domain_management.promoteChildren}
          </label>
          <label className="flex items-center gap-2 text-sm text-red-600 dark:text-red-400">
            <input type="radio" name="delete-option" checked={!promoteChildren} onChange={() => setPromoteChildren(false)} className="accent-red-600" />
            {t.wiki.domain_management.cascadeDelete}
          </label>
        </fieldset>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            {t.wiki.domain_management.cancel}
          </button>
          <button type="button" onClick={() => onConfirm(promoteChildren)} className="rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700">
            {t.wiki.domain_management.confirm}
          </button>
        </div>
        </div>
      </FocusTrap>
    </div>
  );
}
