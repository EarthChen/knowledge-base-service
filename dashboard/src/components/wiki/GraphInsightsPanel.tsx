import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Loader2, Network } from "lucide-react";
import { useMemo, useState } from "react";
import { getGraphInsights, ApiError } from "../../api/client";
import type { GraphInsightCategory, GraphInsightItem } from "../../api/types";

type Props = {
  repository: string;
};

const CATEGORY_LABELS: Record<GraphInsightCategory, string> = {
  isolated: "Isolated entities",
  circular_dep: "Circular dependencies",
  cross_layer: "Cross-layer violations",
  low_cohesion: "Low cohesion modules",
  bridge: "Bridge nodes",
};

function insightSeverityClass(sev: GraphInsightItem["severity"]): string {
  if (sev === "critical") return "bg-red-100 text-red-800 ring-red-200";
  if (sev === "warning") return "bg-amber-100 text-amber-900 ring-amber-200";
  return "bg-sky-100 text-sky-800 ring-sky-200";
}

function groupByCategory(items: GraphInsightItem[]): Map<GraphInsightCategory, GraphInsightItem[]> {
  const m = new Map<GraphInsightCategory, GraphInsightItem[]>();
  for (const it of items) {
    const cat = it.category;
    const list = m.get(cat) ?? [];
    list.push(it);
    m.set(cat, list);
  }
  return m;
}

export default function GraphInsightsPanel({ repository }: Props) {
  const query = useQuery({
    queryKey: ["graph-insights", repository],
    queryFn: () => getGraphInsights(repository),
    enabled: Boolean(repository?.trim()),
    staleTime: 60_000,
  });

  const grouped = useMemo(() => {
    const insights = query.data?.insights;
    if (!insights?.length) return new Map<GraphInsightCategory, GraphInsightItem[]>();
    return groupByCategory(insights);
  }, [query.data]);

  const categories = useMemo(
    () =>
      (Object.keys(CATEGORY_LABELS) as GraphInsightCategory[]).filter((c) =>
        grouped.has(c),
      ),
    [grouped],
  );

  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const k of Object.keys(CATEGORY_LABELS) as GraphInsightCategory[]) {
      init[k] = true;
    }
    return init;
  });

  const toggle = (key: string) => {
    setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-900">
          <Network size={18} className="text-violet-600" aria-hidden />
          Graph insights
        </div>
        {query.isFetching && (
          <span className="inline-flex items-center gap-1 text-xs text-gray-500">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Loading…
          </span>
        )}
      </div>

      <div className="space-y-4 px-4 py-4">
        <p className="text-xs text-gray-500">
          Architecture signals from{" "}
          <code className="rounded bg-gray-100 px-1">GET /api/v1/graph/insights/…</code>.
        </p>

        {query.isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
            {query.error instanceof ApiError ? query.error.message : String(query.error)}
          </div>
        )}

        {query.data?.graph_stats && (
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(query.data.graph_stats).map(([k, v]) => (
              <span
                key={k}
                className="rounded-full bg-gray-100 px-2.5 py-1 font-medium text-gray-700 ring-1 ring-gray-200"
              >
                {k.replace(/_/g, " ")}: {v}
              </span>
            ))}
            {query.data.analyzed_at && (
              <span className="self-center text-gray-400">
                Analyzed {new Date(query.data.analyzed_at).toLocaleString()}
              </span>
            )}
          </div>
        )}

        {query.isLoading && (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Fetching insights…
          </div>
        )}

        {query.data && categories.length === 0 && (
          <p className="text-sm text-gray-600">No insight items returned for this repository.</p>
        )}

        {query.data &&
          categories.map((cat) => {
            const items: GraphInsightItem[] = grouped.get(cat) ?? [];
            const isOpen = open[cat] !== false;
            return (
              <div key={cat} className="rounded-lg border border-gray-100 bg-gray-50/60 shadow-inner">
                <button
                  type="button"
                  onClick={() => toggle(cat)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
                >
                  <span className="text-sm font-semibold text-gray-900">
                    {CATEGORY_LABELS[cat]}
                    <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-xs font-normal text-gray-600 ring-1 ring-gray-200">
                      {items.length}
                    </span>
                  </span>
                  {isOpen ? (
                    <ChevronUp size={18} className="shrink-0 text-gray-500" />
                  ) : (
                    <ChevronDown size={18} className="shrink-0 text-gray-500" />
                  )}
                </button>
                {isOpen && (
                  <ul className="space-y-2 border-t border-gray-100 px-3 py-3">
                    {items.map((it, idx) => (
                      <li
                        key={`${it.title}-${idx}`}
                        className="rounded-md border border-white bg-white px-3 py-2 shadow-sm"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${insightSeverityClass(it.severity)}`}
                          >
                            {it.severity}
                          </span>
                          <span className="text-sm font-medium text-gray-900">{it.title}</span>
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-gray-600">{it.description}</p>
                        {it.entities.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {it.entities.map((e) => (
                              <code
                                key={e}
                                className="max-w-full truncate rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-800"
                              >
                                {e}
                              </code>
                            ))}
                          </div>
                        )}
                        {it.suggestion && (
                          <p className="mt-2 text-xs text-gray-500">{it.suggestion}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}

      </div>
    </section>
  );
}
