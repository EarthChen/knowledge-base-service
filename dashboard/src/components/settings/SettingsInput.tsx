type Props = {
  label: string;
  value: string;
  onChange: (val: string) => void;
  type?: "text" | "number";
  placeholder?: string;
  source?: string;
  description?: string;
};

export default function SettingsInput({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  source,
  description,
}: Props) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-gray-600 dark:text-gray-400">{label}</label>
        {source && <span className="text-[10px] text-gray-400">{source}</span>}
      </div>
      {description && <p className="text-xs text-gray-400 dark:text-gray-500">{description}</p>}
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
      />
    </div>
  );
}
