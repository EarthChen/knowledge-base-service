import { useEffect, useState } from "react";
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
import {
  Code,
  Blocks,
  Package,
  FileText,
  ArrowRightLeft,
  Network,
  Zap,
  GitBranch,
  Layers,
  Database,
  Server,
  FileStack,
  ListTree,
  Activity,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useHealthStats, useP2Stats, useStats } from "../api/hooks";
import { useI18n } from "../i18n/context";
import StatCard from "../components/StatCard";
import { SkeletonCard } from "../components/Skeleton";
import QuickStartBanner from "../components/QuickStartBanner";

ChartJS.register(ArcElement, Tooltip, Legend, CategoryScale, LinearScale, BarElement);

function coverageBarColor(ratio: number): string {
  if (ratio > 0.8) return "bg-emerald-500";
  if (ratio > 0.5) return "bg-amber-400";
  return "bg-red-500";
}

function stalenessBadgeClass(hours: number | null): string {
  if (hours === null) return "bg-gray-100 text-gray-600";
  if (hours < 24) return "bg-emerald-100 text-emerald-800";
  if (hours < 72) return "bg-amber-100 text-amber-900";
  return "bg-red-100 text-red-800";
}

function orphanTextClass(ratio: number): string {
  if (ratio < 0.05) return "text-emerald-700";
  if (ratio < 0.2) return "text-amber-700";
  return "text-red-700";
}

export default function Overview() {
  const [showQuickStart, setShowQuickStart] = useState(true);
  useEffect(() => {
    try {
      const raw = localStorage.getItem("kb_onboarding");
      const s = raw ? (JSON.parse(raw) as { dismissed?: boolean }) : {};
      setShowQuickStart(!s?.dismissed);
    } catch {
      setShowQuickStart(true);
    }
  }, []);

  const { data: stats, isLoading, error } = useStats();
  const { data: p2, isLoading: p2Loading, error: p2Error } = useP2Stats();
  const {
    data: health,
    isLoading: healthLoading,
    error: healthError,
  } = useHealthStats();
  const { t } = useI18n();
  const navigate = useNavigate();

  if (error) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-600">
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
            borderColor: "#f1f5f9",
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

  const archSorted = p2
    ? Object.entries(p2.architecture_layers).sort((a, b) => b[1] - a[1])
    : [];

  const archBarData =
    archSorted.length > 0
      ? {
          labels: archSorted.map(([name]) => name),
          datasets: [
            {
              label: "Count",
              data: archSorted.map(([, v]) => v),
              backgroundColor: "rgba(249, 115, 22, 0.75)",
              borderColor: "rgb(234, 88, 12)",
              borderWidth: 1,
            },
          ],
        }
      : null;

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-semibold text-gray-900">{t.overview.title}</h2>

      {showQuickStart ? (
        <QuickStartBanner onDismiss={() => setShowQuickStart(false)} />
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {isLoading ? (
          Array.from({ length: 4 }).map((_, i) => <SkeletonCard key={i} />)
        ) : (
          <>
            <StatCard
              label={t.overview.functions}
              value={stats?.function_count ?? 0}
              icon={Code}
              color="bg-emerald-50 text-emerald-700"
            />
            <StatCard
              label={t.overview.classes}
              value={stats?.class_count ?? 0}
              icon={Blocks}
              color="bg-sky-50 text-sky-700"
            />
            <StatCard
              label={t.overview.modules}
              value={stats?.module_count ?? 0}
              icon={Package}
              color="bg-purple-50 text-purple-700"
            />
            <StatCard
              label={t.overview.documents}
              value={stats?.document_count ?? 0}
              icon={FileText}
              color="bg-amber-50 text-amber-700"
            />
          </>
        )}
      </div>

      <div className="rounded-xl border border-teal-200/80 bg-gradient-to-br from-teal-50/90 to-sky-50/50 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold text-teal-950">
              <Activity size={18} className="text-teal-600" />
              {t.overview.knowledgeHealthTitle}
            </h3>
            <p className="mt-1 max-w-xl text-xs text-teal-900/70">{t.overview.knowledgeHealthSubtitle}</p>
          </div>
          {health && !healthLoading ? (
            <p className="text-xs text-teal-800/80">
              {t.overview.nodesEdgesSummary
                .replace("{nodes}", String(health.total_nodes))
                .replace("{edges}", String(health.total_edges))}
            </p>
          ) : null}
        </div>

        {healthError && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50/90 px-3 py-2 text-xs text-amber-900">
            {(healthError as Error).message}
          </div>
        )}

        {healthLoading && !health ? (
          <div className="mt-4 space-y-3">
            <div className="h-9 animate-pulse rounded-lg bg-teal-100/80" />
            <div className="h-9 animate-pulse rounded-lg bg-teal-100/80" />
            <div className="h-9 animate-pulse rounded-lg bg-teal-100/80" />
          </div>
        ) : null}

        {health ? (
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-lg border border-white/80 bg-white/70 p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">{t.overview.indexCoverageLabel}</p>
              <div className="mt-2 flex items-center gap-2">
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200">
                  <div
                    className={`h-full rounded-full transition-all ${coverageBarColor(health.index_coverage)}`}
                    style={{
                      width: `${Math.min(100, Math.max(0, health.index_coverage * 100))}%`,
                    }}
                  />
                </div>
                <span className="text-sm font-semibold tabular-nums text-gray-900">
                  {(health.index_coverage * 100).toFixed(1)}%
                </span>
              </div>
            </div>

            <div className="rounded-lg border border-white/80 bg-white/70 p-3 shadow-sm">
              <p className="text-xs font-medium text-gray-500">{t.overview.stalenessLabel}</p>
              <div className="mt-2">
                <span
                  className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${stalenessBadgeClass(
                    health.staleness_hours,
                  )}`}
                >
                  {health.staleness_hours === null
                    ? t.overview.neverIndexed
                    : health.staleness_hours < 48
                      ? `${health.staleness_hours.toFixed(1)} ${t.overview.hoursShort}`
                      : `${(health.staleness_hours / 24).toFixed(1)} ${t.overview.daysShort}`}
                </span>
              </div>
              <p className="mt-2 text-[11px] text-gray-500">
                {t.overview.lastIndexedLabel}:{" "}
                {health.last_indexed_at
                  ? new Date(health.last_indexed_at).toLocaleString()
                  : "—"}
              </p>
            </div>

            <div className="rounded-lg border border-white/80 bg-white/70 p-3 shadow-sm sm:col-span-2 lg:col-span-1">
              <p className="text-xs font-medium text-gray-500">{t.overview.orphanRatioLabel}</p>
              <p className={`mt-2 text-lg font-semibold tabular-nums ${orphanTextClass(health.orphan_ratio)}`}>
                {(health.orphan_ratio * 100).toFixed(1)}%
              </p>
            </div>
          </div>
        ) : null}
      </div>

      {stats && (
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-500">
            <ArrowRightLeft size={16} />
            {t.overview.edgeCounts}
          </div>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-5">
            {edgePairs.map(([label, count]) => (
              <div key={label as string} className="text-center">
                <p className="text-xs text-gray-400">{label as string}</p>
                <p className="mt-0.5 text-lg font-semibold text-gray-900">
                  {count as number}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        {nodeData && (
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h3 className="mb-4 text-sm font-medium text-gray-500">
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
                      labels: { color: "#64748b", padding: 12, font: { size: 11 } },
                    },
                  },
                }}
              />
            </div>
          </div>
        )}

        {edgeData && (
          <div className="rounded-xl border border-gray-200 bg-white p-5">
            <h3 className="mb-4 text-sm font-medium text-gray-500">
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
                      ticks: { color: "#64748b", font: { size: 10 } },
                      grid: { color: "rgba(203,213,225,0.5)" },
                    },
                    y: {
                      beginAtZero: true,
                      ticks: { color: "#64748b" },
                      grid: { color: "rgba(203,213,225,0.5)" },
                    },
                  },
                  plugins: { legend: { display: false } },
                }}
              />
            </div>
          </div>
        )}
      </div>

      <div className="space-y-4 border-t border-orange-100 pt-6">
        <h3 className="text-base font-semibold text-orange-950">{t.overview.p2Title}</h3>

        {p2Error && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            {t.overview.failedToLoadStats}: {(p2Error as Error).message}
          </div>
        )}

        {!p2Error && archBarData && (
          <div className="rounded-xl border border-orange-200/80 bg-gradient-to-br from-orange-50/80 to-rose-50/40 p-5">
            <h4 className="mb-4 flex items-center gap-2 text-sm font-medium text-orange-900/80">
              <Layers size={16} className="text-orange-600" />
              {t.overview.architectureLayers}
            </h4>
            <div className="relative h-72 min-h-[12rem]">
              <Bar
                data={archBarData}
                options={{
                  indexAxis: "y",
                  responsive: true,
                  maintainAspectRatio: false,
                  onClick: (_event, elements) => {
                    if (!elements.length) return;
                    const idx = elements[0].index;
                    const label = archSorted[idx]?.[0];
                    if (label) {
                      navigate(`/architecture?layer=${encodeURIComponent(label)}`);
                    }
                  },
                  onHover: (event, elements) => {
                    const canvas = event.native?.target as HTMLCanvasElement | undefined;
                    if (canvas) {
                      canvas.style.cursor = elements.length ? "pointer" : "default";
                    }
                  },
                  scales: {
                    x: {
                      beginAtZero: true,
                      ticks: { color: "#64748b" },
                      grid: { color: "rgba(203,213,225,0.5)" },
                    },
                    y: {
                      ticks: { color: "#64748b", font: { size: 10 } },
                      grid: { color: "rgba(203,213,225,0.5)" },
                    },
                  },
                  plugins: { legend: { display: false } },
                }}
              />
            </div>
          </div>
        )}

        {!p2Error && p2Loading && !p2 && (
          <div className="rounded-xl border border-orange-200/80 bg-white p-5">
            <div className="mb-4 h-4 w-40 animate-pulse rounded bg-orange-100" />
            <div className="relative h-72 animate-pulse rounded-lg bg-orange-50/80" />
          </div>
        )}

        {!p2Error && !p2Loading && p2 && archSorted.length === 0 && (
          <div className="rounded-xl border border-dashed border-orange-200 bg-orange-50/30 p-6 text-center text-sm text-orange-900/70">
            {t.overview.architectureLayers}: —
          </div>
        )}

        {!p2Error && (
          <div className="space-y-5">
            <div>
              <p className="mb-3 text-sm font-medium text-indigo-900/80">{t.overview.crossRepo}</p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {p2Loading && !p2 ? (
                  <>
                    {Array.from({ length: 3 }).map((_, i) => (
                      <SkeletonCard key={i} />
                    ))}
                  </>
                ) : (
                  p2 && (
                    <>
                      <StatCard
                        label={t.overview.diDependencies}
                        value={p2.cross_repo.di_dependency_edges}
                        icon={Network}
                        color="bg-indigo-50 text-indigo-700"
                      />
                      <StatCard
                        label={t.overview.crossRepoRpc}
                        value={p2.cross_repo.cross_repo_call_edges}
                        icon={GitBranch}
                        color="bg-rose-50 text-rose-700"
                      />
                      <StatCard
                        label={t.overview.entityTables}
                        value={p2.cross_repo.entity_table_edges}
                        icon={Database}
                        color="bg-orange-50 text-orange-700"
                      />
                    </>
                  )
                )}
              </div>
            </div>

            <div>
              <p className="mb-3 text-sm font-medium text-rose-900/80">{t.overview.eventTracking}</p>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {p2Loading && !p2 ? (
                  <>
                    {Array.from({ length: 3 }).map((_, i) => (
                      <SkeletonCard key={`ev-${i}`} />
                    ))}
                  </>
                ) : (
                  p2 && (
                    <>
                      <StatCard
                        label={t.overview.kafkaTopics}
                        value={p2.event_tracking.kafka_topics}
                        icon={Layers}
                        color="bg-amber-50 text-amber-800"
                      />
                      <StatCard
                        label={t.overview.eventProducers}
                        value={p2.event_tracking.producers}
                        icon={Zap}
                        color="bg-orange-50 text-orange-800"
                      />
                      <StatCard
                        label={t.overview.eventConsumers}
                        value={p2.event_tracking.consumers}
                        icon={Server}
                        color="bg-rose-50 text-rose-800"
                      />
                    </>
                  )
                )}
              </div>
            </div>

            <div>
              <p className="mb-3 text-sm font-medium text-violet-900/80">{t.overview.rpcContracts}</p>
              <div className="grid gap-4 sm:grid-cols-2">
                {p2Loading && !p2 ? (
                  <>
                    {Array.from({ length: 2 }).map((_, i) => (
                      <SkeletonCard key={`rpc-${i}`} />
                    ))}
                  </>
                ) : (
                  p2 && (
                    <>
                      <StatCard
                        label={t.overview.totalContracts}
                        value={p2.rpc_contracts.total_contracts}
                        icon={FileStack}
                        color="bg-violet-50 text-violet-700"
                      />
                      <StatCard
                        label={t.overview.contractMethods}
                        value={p2.rpc_contracts.contract_methods}
                        icon={ListTree}
                        color="bg-fuchsia-50 text-fuchsia-700"
                      />
                    </>
                  )
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
