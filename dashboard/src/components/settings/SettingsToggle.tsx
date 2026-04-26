type Props = {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (val: boolean) => void;
  source?: string;
};

export default function SettingsToggle({ label, description, checked, onChange, source }: Props) {
  return (
    <label className="flex items-center justify-between gap-3 rounded-lg border border-gray-100 bg-gray-50/50 px-3 py-2 dark:border-gray-700 dark:bg-gray-800/40">
      <div>
        <span className="text-sm text-gray-700 dark:text-gray-200">{label}</span>
        {description && <p className="text-xs text-gray-400 dark:text-gray-500">{description}</p>}
      </div>
      <div className="flex items-center gap-2">
        {source && <span className="text-[10px] text-gray-400">{source}</span>}
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="h-4 w-4 rounded border-gray-300 text-sky-600 focus:ring-sky-500 dark:border-gray-600"
        />
      </div>
    </label>
  );
}
