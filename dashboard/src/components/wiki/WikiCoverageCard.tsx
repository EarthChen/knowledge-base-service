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

export default function WikiCoverageCard({ businessId }: Props) {
  const { t } = useI18n();
  const isDark = useIsDarkMode();
  const chartTick = isDark ? "#d1d5db" : "#4b5563";
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
        {(q.error as Error).message}
      </div>
    );
  }

  const data = q.data;
  if (!data) return null;

  const core = data.core_coverage ?? 0;
  const standard = data.standard_coverage ?? 0;
  const stale = data.stale_page_count ?? 0;
  const gaps = data.knowledge_gap_count ?? 0;

  const chartData = {
    labels: ["Core", "Standard", "Stale pages", "Knowledge gaps"],
    datasets: [
      {
        data: [Math.max(0, core), Math.max(0, standard), Math.max(0, stale), Math.max(0, gaps)],
        backgroundColor: [
          "rgba(14, 165, 233, 0.85)",
          "rgba(52, 211, 153, 0.85)",
          "rgba(251, 191, 36, 0.85)",
          "rgba(248, 113, 113, 0.85)",
        ],
        borderWidth: 0,
      },
    ],
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {t.wiki.coverageTitle}
        </h3>
        {stale > 0 ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
            <AlertTriangle className="size-3.5 shrink-0" aria-hidden />
            {stale} stale
          </span>
        ) : null}
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 sm:items-center">
        <div className="relative mx-auto h-44 w-full max-w-[200px]">
          <Doughnut
            data={chartData}
            options={{
              responsive: true,
              maintainAspectRatio: false,
              cutout: "70%",
              plugins: {
                legend: {
                  position: "bottom",
                  labels: { color: chartTick, padding: 10, font: { size: 10 } },
                },
              },
            }}
          />
        </div>
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Core</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{core}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Standard</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{standard}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Stale</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{stale}</dd>
          </div>
          <div>
            <dt className="text-gray-500 dark:text-gray-400">Gaps</dt>
            <dd className="font-semibold tabular-nums text-gray-900 dark:text-gray-100">{gaps}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
