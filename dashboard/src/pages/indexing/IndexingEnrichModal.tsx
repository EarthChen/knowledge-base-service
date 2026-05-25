import { useId } from "react";
import FocusTrap from "../../components/FocusTrap";
import { Loader2 } from "lucide-react";
import { useI18n } from "../../i18n/context";
import type { Repository } from "../../api/types";

const inputClass =
  "w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:placeholder-gray-500 dark:focus:border-sky-500 dark:focus:ring-sky-600";

interface Props {
  open: boolean;
  repositories: Repository[];
  enrichRepository: string;
  enrichForce: boolean;
  isPending: boolean;
  onRepositoryChange: (value: string) => void;
  onForceChange: (value: boolean) => void;
  onSubmit: (e: React.FormEvent) => void;
  onClose: () => void;
}

export function IndexingEnrichModal({
  open,
  repositories,
  enrichRepository,
  enrichForce,
  isPending,
  onRepositoryChange,
  onForceChange,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useI18n();
  const repositoryLabelId = useId();
  const repositoryInputId = useId();
  const forceCheckboxId = useId();

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 dark:bg-black/60"
      role="dialog"
      aria-modal="true"
      aria-labelledby="enrich-modal-title"
    >
      <FocusTrap onEscape={onClose}>
        <div className="w-full max-w-md rounded-xl border border-gray-200 bg-white p-6 shadow-lg dark:border-gray-600 dark:bg-gray-900">
          <h3 id="enrich-modal-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
            {t.indexing.enrichTitle}
          </h3>
          <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">{t.indexing.enrichDesc}</p>
          <form onSubmit={onSubmit} className="mt-4 space-y-4">
            <div className="space-y-1">
              <label
                id={repositoryLabelId}
                htmlFor={repositoryInputId}
                className="block text-xs font-medium text-gray-500 dark:text-gray-400"
              >
                {t.indexing.enrichRepository}
              </label>
              {repositories.length > 0 ? (
                <select
                  id={repositoryInputId}
                  aria-labelledby={repositoryLabelId}
                  value={enrichRepository}
                  onChange={(e) => onRepositoryChange(e.target.value)}
                  className={inputClass}
                >
                  <option value="">{t.indexing.enrichRepository}</option>
                  {repositories.map((r) => (
                    <option key={r.repository} value={r.repository}>
                      {r.repository}
                    </option>
                  ))}
                </select>
              ) : (
                <>
                  <p className="text-xs text-amber-700 dark:text-amber-400">{t.indexing.enrichManualHint}</p>
                  <input
                    id={repositoryInputId}
                    aria-labelledby={repositoryLabelId}
                    type="text"
                    value={enrichRepository}
                    onChange={(e) => onRepositoryChange(e.target.value)}
                    placeholder={t.indexing.repoPlaceholder}
                    className={inputClass}
                  />
                </>
              )}
            </div>
            <label
              htmlFor={forceCheckboxId}
              className="flex cursor-pointer items-center gap-2 text-sm text-gray-700 dark:text-gray-300"
            >
              <input
                id={forceCheckboxId}
                type="checkbox"
                checked={enrichForce}
                onChange={(e) => onForceChange(e.target.checked)}
                className="accent-sky-500"
              />
              {t.indexing.enrichForce}
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 dark:hover:bg-gray-700"
              >
                {t.businesses.cancel}
              </button>
              <button
                type="submit"
                disabled={isPending}
                className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-4 py-2 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50 dark:bg-sky-600 dark:hover:bg-sky-500"
              >
                {isPending && <Loader2 size={16} className="animate-spin" />}
                {t.indexing.enrichTrigger}
              </button>
            </div>
          </form>
        </div>
      </FocusTrap>
    </div>
  );
}
