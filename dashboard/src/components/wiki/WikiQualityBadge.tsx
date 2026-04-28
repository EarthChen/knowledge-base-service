import { useI18n } from "../../i18n/context";

type Props = { score: number; className?: string };

export default function WikiQualityBadge({ score, className = "" }: Props) {
  const { t } = useI18n();
  const pct = Math.round(score * 100);
  const color = score >= 0.8 ? "green" : score >= 0.6 ? "yellow" : "red";

  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
        color === "green"
          ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
          : color === "yellow"
            ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300"
            : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
      } ${className}`}
    >
      {t.wiki.qualityBadge.replace("{pct}", String(pct))}
    </span>
  );
}
