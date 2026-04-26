import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Doughnut } from "react-chartjs-2";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useWikiCoverage } from "../../hooks/useWikiCoverage";
import { useIsDarkMode } from "../../hooks/useIsDarkMode";
import { useI18n } from "../../i18n/context";

ChartJS.register(ArcElement, Tooltip, Legend);

type Props = {
  businessId: string;
};

function getErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export default function WikiCoverageCard({ businessId }: Props) {
  const { t } = useI18n();
  const isDark = useIsDarkMode();
  const q = useWikiCoverage(businessId);

  if (q.isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white p-6 text-sm text-gray-500 dark:border-gray-700 dark:bg-gray-900 dark:text-gray-400">
        <Loader2 className="size-4 animate-spin" aria-hidden />
        {t.common.loading}
      </div>
    );
  }

  if (q.isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50/80 p-4 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-200">
        {getErrorMessage(q.error)}
      </div>
    );
  }

  const data = q.data;
  if (!data) return null;

  const covered = data.covered_entities ?? 0;
  const total = data.total_entities ?? 0;
  const uncovered = Math.max(0, total - covered);
  const corePct = Math.round((data.core_coverage ?? 0) * 100);
  const stdPct = Math.round((data.standard_coverage ?? 0) * 100);
  const stale = data.stale_page_count ?? 0;
  const gaps = data.knowledge_gap_count ?? 0;

  const chartData = {
    labels: [t.wiki.covered, t.wiki.uncovered],
    datasets: [
      {
        data: [covered, uncovered || (total === 0 ? 1 : 0)],
        backgroundColor: [
          "rgba(14, 165, 233, 0.85)",
          isDark ? "rgba(55, 65, 81, 0.6)" : "rgba(229, 231, 235, 0.85)",
        ],
        borderWidth: 0,
      },
    ],
  };

  const overallPct = total > 0 ? Math.round((covered / total) * 100) : 0;

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {t.wiki.coverageTitle}
        </h3>
        {stale > 0 ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
            {stale} {t.wiki.staleLabel}
          </span>
        ) : null}
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 sm:items-center">
        <div className="relative mx-auto flex h-44 w-full max-w-[200px] items-center justify-center">
          <Doughnut
            data={chartData}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              cutout: "70%",
              plugins: {
                legend: { display: false },
              },
            }}
          />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold text-gray-900 dark:text-gray-100">
              {overallPct}%
            </span>
            <span className="text-[10px] text-gray-500 dark:text-gray-400">
              {covered}/{total}
            </span>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-gray-500 dark:text-gray-400">{t.wiki.coreLabel}</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{corePct}%</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">{t.wiki.standardLabel}</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{stdPct}%</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">{t.wiki.staleLabel}</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{stale}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">{t.wiki.gapsLabel}</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{gaps}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
