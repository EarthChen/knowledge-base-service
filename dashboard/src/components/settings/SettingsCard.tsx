import type { ReactNode } from "react";

type Props = {
  title: string;
  description?: string;
  icon?: ReactNode;
  children: ReactNode;
  saving?: boolean;
  onSave?: () => void;
  saveLabel?: string;
};

export default function SettingsCard({
  title,
  description,
  icon,
  children,
  saving,
  onSave,
  saveLabel,
}: Props) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {icon}
          <div>
            <h3 className="text-sm font-medium text-gray-800 dark:text-gray-100">{title}</h3>
            {description && <p className="text-xs text-gray-500 dark:text-gray-400">{description}</p>}
          </div>
        </div>
        {onSave && (
          <button
            type="button"
            onClick={onSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500 disabled:opacity-50"
          >
            {saving ? "..." : (saveLabel ?? "Save")}
          </button>
        )}
      </div>
      <div className="mt-4 space-y-3">{children}</div>
    </div>
  );
}
