import { BarChart2 } from "lucide-react";
import { useI18n } from "../../i18n/context";

interface QualitySummary {
  avg_score: number;
  evaluated_count: number;
  low_quality_count: number;
}

type Props = {
  summary: QualitySummary | null | undefined;
  isLoading?: boolean;
};

export default function WikiQualitySummary({ summary, isLoading }: Props) {
  const { t } = useI18n();

  if (isLoading) {
    return (
      <div className="animate-pulse rounded-lg border border-gray-200 bg-white p-4 dark:border-gray-700 dark:bg-gray-900">
        <div className="h-4 w-24 rounded bg-gray-200 dark:bg-gray-700" />
      </div>
    );
  }

  if (!summary || summary.evaluated_count === 0) return null;

  const pct = Math.round(summary.avg_score * 100);
  const color =
    summary.avg_score >= 0.8 ? "green" : summary.avg_score >= 0.6 ? "yellow" : "red";

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex items-center gap-2 text-sm font-medium text-gray-700 dark:text-gray-300">
        <BarChart2 size={16} />
        <span>{t.wiki.docQualityTitle}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span
          className={`text-2xl font-bold ${
            color === "green"
              ? "text-green-600 dark:text-green-400"
              : color === "yellow"
                ? "text-yellow-600 dark:text-yellow-400"
                : "text-red-600 dark:text-red-400"
          }`}
        >
          {pct}%
        </span>
        <span className="text-xs text-gray-500">{t.wiki.docQualityAvg}</span>
      </div>
      <div className="mt-2 flex gap-4 text-xs text-gray-500 dark:text-gray-400">
        <span>{t.wiki.docQualityEvaluated.replace("{count}", String(summary.evaluated_count))}</span>
        {summary.low_quality_count > 0 && (
          <span className="text-red-500">
            {t.wiki.docQualityBelowThreshold.replace("{count}", String(summary.low_quality_count))}
          </span>
        )}
      </div>
    </div>
  );
}
