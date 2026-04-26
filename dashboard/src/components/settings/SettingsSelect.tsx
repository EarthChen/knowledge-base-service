import { useId } from "react";

type Props = {
  label: string;
  value: string;
  onChange: (val: string) => void;
  options: { value: string; label: string }[];
  source?: string;
};

export default function SettingsSelect({ label, value, onChange, options, source }: Props) {
  const id = useId();
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-xs font-medium text-gray-600 dark:text-gray-400">
          {label}
        </label>
        {source && <span className="text-[10px] text-gray-400">{source}</span>}
      </div>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
