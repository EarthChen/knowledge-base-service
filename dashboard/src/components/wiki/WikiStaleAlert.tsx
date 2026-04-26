import { AlertTriangle } from "lucide-react";
import { useI18n } from "../../i18n/context";

interface WikiStaleAlertProps {
  /** Locale-formatted date string shown after the i18n message */
  generatedAtLabel: string;
  isStale: boolean;
}

export default function WikiStaleAlert({ generatedAtLabel, isStale }: WikiStaleAlertProps) {
  const { t } = useI18n();
  if (!isStale) return null;

  return (
    <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-300">
      <AlertTriangle size={16} className="shrink-0" />
      <span>{t.wiki.staleWarning.replace("{date}", generatedAtLabel)}</span>
    </div>
  );
}
