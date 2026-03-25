import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
  CategoryScale,
  LinearScale,
  BarElement,
} from "chart.js";
import { Doughnut, Bar } from "react-chartjs-2";
import { Code, Blocks, Package, FileText, ArrowRightLeft } from "lucide-react";
import { useStats } from "../api/hooks";
import { useI18n } from "../i18n/context";
import StatCard from "../components/StatCard";
import { SkeletonCard } from "../components/Skeleton";

ChartJS.register(ArcElement, Tooltip, Legend, CategoryScale, LinearScale, BarElement);

export default function Overview() {
  const { data: stats, isLoading, error } = useStats();
  const { t } = useI18n();

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-red-400">
        {t.overview.failedToLoadStats}: {(error as Error).message}
      </div>
    );
  }

  const nodeData = stats
    ? {
        labels: [t.overview.functions, t.overview.classes, t.overview.modules, t.overview.documents],
        datasets: [
          {
            data: [
              stats.function_count,
              stats.class_count,
              stats.module_count,
              stats.document_count,
            ],
            backgroundColor: [
              "rgba(16, 185, 129, 0.85)",
              "rgba(14, 165, 233, 0.85)",
              "rgba(168, 85, 247, 0.85)",
              "rgba(251, 191, 36, 0.85)",
            ],
            borderColor: "#172033",
            borderWidth: 2,
          },
        ],
      }
    : null;

  const edgeLabels = [
    t.overview.calls,
    t.overview.inherits,
    t.overview.imports,
    t.overview.contains,
    t.overview.references,
  ];

  const edgeData = stats
    ? {
        labels: edgeLabels,
        datasets: [
          {
            label: "Count",
            data: [
              stats.calls_count,
              stats.inherits_count,
              stats.imports_count,
              stats.contains_count,
              stats.references_count,
            ],
            backgroundColor: "rgba(14, 165, 233, 0.7)",
            borderColor: "rgb(14, 165, 233)",
            borderWidth: 1,
          },
        ],
      }
    : null;

  const edgePairs = stats
    ? [
        [t.overview.calls, stats.calls_count],
        [t.overview.inherits, stats.inherits_count],
        [t.overview.imports, stats.imports_count],
        [t.overview.contains, stats.contains_count],
        [t.overview.references, stats.references_count],
      ]
    : [];

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-white">{t.overview.title}</h2>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
        ) : (
          <>
            <StatCard
              label={t.overview.functions}
              value={stats?.function_count ?? 0}
              icon={Code}
              color="bg-emerald-500/15 text-emerald-400"
            />
            <StatCard
              label={t.overview.classes}
              value={stats?.class_count ?? 0}
              icon={Blocks}
              color="bg-sky-500/15 text-sky-400"
            />
            <StatCard
              label={t.overview.modules}
              value={stats?.module_count ?? 0}
              icon={Package}
              color="bg-purple-500/15 text-purple-400"
            />
            <StatCard
              label={t.overview.documents}
              value={stats?.document_count ?? 0}
              icon={FileText}
              color="bg-amber-500/15 text-amber-400"
            />
          </>
        )}
      </div>

      {stats && (
        <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-400">
            <ArrowRightLeft size={16} />
            {t.overview.edgeCounts}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-5">
            {edgePairs.map(([label, count]) => (
              <div key={label as string} className="text-center">
                <p className="text-xs text-slate-500">{label as string}</p>
                <p className="mt-0.5 text-lg font-semibold text-white">
                  {count as number}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {nodeData && (
          <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
            <h3 className="mb-4 text-sm font-medium text-slate-400">
              {t.overview.nodeDistribution}
            </h3>
            <div className="relative mx-auto h-64 max-w-xs">
              <Doughnut
                data={nodeData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  plugins: {
                    legend: {
                      position: "bottom",
                      labels: { color: "#cbd5e1", padding: 12, font: { size: 11 } },
                    },
                  },
                }}
              />
            </div>
          </div>
        )}

        {edgeData && (
          <div className="rounded-xl border border-slate-800 bg-slate-850 p-5">
            <h3 className="mb-4 text-sm font-medium text-slate-400">
              {t.overview.edgeDistribution}
            </h3>
            <div className="relative h-64">
              <Bar
                data={edgeData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  scales: {
                    x: {
                      ticks: { color: "#94a3b8", font: { size: 10 } },
                      grid: { color: "rgba(51,65,85,0.4)" },
                    },
                    y: {
                      beginAtZero: true,
                      ticks: { color: "#94a3b8" },
                      grid: { color: "rgba(51,65,85,0.4)" },
                    },
                  },
                  plugins: { legend: { display: false } },
                }}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
