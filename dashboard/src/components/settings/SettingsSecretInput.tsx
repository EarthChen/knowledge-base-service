import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useI18n } from "../../i18n/context";

type Props = {
  label: string;
  value: string;
  onChange: (val: string) => void;
  placeholder?: string;
  source?: string;
};

export default function SettingsSecretInput({ label, value, onChange, placeholder, source }: Props) {
  const { t } = useI18n();
  const id = useId();
  const [show, setShow] = useState(false);
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <label htmlFor={id} className="text-xs font-medium text-gray-600 dark:text-gray-400">
          {label}
        </label>
        {source && <span className="text-[10px] text-gray-400">{source}</span>}
      </div>
      <div className="relative">
        <input
          id={id}
          type={show ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="new-password"
          className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 pr-10 text-sm text-gray-900 outline-none focus:border-sky-400 focus:ring-1 focus:ring-sky-300 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
        />
        <button
          type="button"
          aria-label={show ? t.configSettings.fields.ariaHideSecret : t.configSettings.fields.ariaShowSecret}
          onClick={() => setShow(!show)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
        >
          {show ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
    </div>
  );
}
