import { Clock, History } from "lucide-react";
import { useI18n } from "../../i18n/context";

interface WikiVersionBadgeProps {
  version: number;
  generatedAt: string;
  onClick?: () => void;
}

export default function WikiVersionBadge({ version, generatedAt, onClick }: WikiVersionBadgeProps) {
  const { t } = useI18n();
  let formatted = generatedAt;
  try {
    formatted = new Date(generatedAt).toLocaleDateString();
  } catch {
    /* keep raw */
  }

  const className =
    "inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-[11px] text-gray-600 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400";
  const interactiveClass =
    "transition-colors hover:bg-gray-100 dark:hover:bg-gray-700";

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`${className} ${interactiveClass}`}
      >
        <History size={11} />
        {t.wiki.versionBadge.replace("{version}", String(version))}
        <span className="text-gray-400 dark:text-gray-500">&middot;</span>
        <Clock size={11} />
        {formatted}
      </button>
    );
  }

  return (
    <span className={className}>
      <History size={11} />
      {t.wiki.versionBadge.replace("{version}", String(version))}
      <span className="text-gray-400 dark:text-gray-500">&middot;</span>
      <Clock size={11} />
      {formatted}
    </span>
  );
}
