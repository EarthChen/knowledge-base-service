import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronUp, Loader2, Network } from "lucide-react";
import { useMemo, useState } from "react";
import { getGraphInsights, ApiError } from "../../api/client";
import type { GraphInsightCategory, GraphInsightItem } from "../../api/types";
import type { Translations } from "../../i18n/types";
import { useI18n } from "../../i18n/context";

type Props = {
  repository: string;
};

const GRAPH_INSIGHT_CATEGORY_ORDER: GraphInsightCategory[] = [
  "isolated",
  "circular_dep",
  "cross_layer",
  "low_cohesion",
  "bridge",
];

function categoryLabel(cat: GraphInsightCategory, t: Translations): string {
  switch (cat) {
    case "isolated":
      return t.wiki.graphInsightCategoryIsolated;
    case "circular_dep":
      return t.wiki.graphInsightCategoryCircularDep;
    case "cross_layer":
      return t.wiki.graphInsightCategoryCrossLayer;
    case "low_cohesion":
      return t.wiki.graphInsightCategoryLowCohesion;
    case "bridge":
      return t.wiki.graphInsightCategoryBridge;
  }
}

function insightSeverityClass(sev: GraphInsightItem["severity"]): string {
  if (sev === "critical") {
    return "bg-red-100 text-red-800 ring-red-200 dark:bg-red-950/50 dark:text-red-300 dark:ring-red-900";
  }
  if (sev === "warning") {
    return "bg-amber-100 text-amber-900 ring-amber-200 dark:bg-amber-950/50 dark:text-amber-200 dark:ring-amber-900";
  }
  return "bg-sky-100 text-sky-800 ring-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:ring-sky-800";
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
  const { locale, t } = useI18n();
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
    () => GRAPH_INSIGHT_CATEGORY_ORDER.filter((c) => grouped.has(c)),
    [grouped],
  );

  const [open, setOpen] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const k of GRAPH_INSIGHT_CATEGORY_ORDER) {
      init[k] = true;
    }
    return init;
  });

  const toggle = (key: string) => {
    setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <section className="rounded-xl border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-900 dark:shadow-gray-950/40">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gray-100 px-4 py-3 dark:border-gray-700">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          <Network size={18} className="text-violet-600 dark:text-violet-400" aria-hidden />
          {t.wiki.graphInsightsTitle}
        </div>
        {query.isFetching && (
          <span className="inline-flex items-center gap-1 text-xs text-gray-500 dark:text-gray-400">
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            {t.wiki.graphInsightsLoading}
          </span>
        )}
      </div>

      <div className="space-y-4 px-4 py-4">
        <p className="text-xs text-gray-500 dark:text-gray-400">
          {t.wiki.graphInsightsIntroBefore}{" "}
          <code className="rounded bg-gray-100 px-1 dark:bg-gray-800 dark:text-gray-300">GET /api/v1/graph/insights/…</code>
          {t.wiki.graphInsightsIntroAfter}
        </p>

        {query.isError && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
            {query.error instanceof ApiError ? query.error.message : String(query.error)}
          </div>
        )}

        {query.data?.graph_stats && (
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(query.data.graph_stats).map(([k, v]) => (
              <span
                key={k}
                className="rounded-full bg-gray-100 px-2.5 py-1 font-medium text-gray-700 ring-1 ring-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:ring-gray-600"
              >
                {k.replace(/_/g, " ")}: {v}
              </span>
            ))}
            {query.data.analyzed_at && (
              <span className="self-center text-gray-400 dark:text-gray-500">
                {t.wiki.graphInsightsAnalyzedPrefix}{" "}
                {new Date(query.data.analyzed_at).toLocaleString(
                  locale === "zh" ? "zh-CN" : undefined,
                )}
              </span>
            )}
          </div>
        )}

        {query.isLoading && (
          <div className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            {t.wiki.graphInsightsFetching}
          </div>
        )}

        {query.data && categories.length === 0 && (
          <p className="text-sm text-gray-600 dark:text-gray-400">{t.wiki.graphInsightsNoItems}</p>
        )}

        {query.data &&
          categories.map((cat) => {
            const items: GraphInsightItem[] = grouped.get(cat) ?? [];
            const isOpen = open[cat] !== false;
            return (
              <div key={cat} className="rounded-lg border border-gray-100 bg-gray-50/60 shadow-inner dark:border-gray-700 dark:bg-gray-800/40">
                <button
                  type="button"
                  onClick={() => toggle(cat)}
                  className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left"
                >
                  <span className="text-sm font-semibold text-gray-900 dark:text-gray-100">
                    {categoryLabel(cat, t)}
                    <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-xs font-normal text-gray-600 ring-1 ring-gray-200 dark:bg-gray-900 dark:text-gray-400 dark:ring-gray-600">
                      {items.length}
                    </span>
                  </span>
                  {isOpen ? (
                    <ChevronUp size={18} className="shrink-0 text-gray-500 dark:text-gray-400" />
                  ) : (
                    <ChevronDown size={18} className="shrink-0 text-gray-500 dark:text-gray-400" />
                  )}
                </button>
                {isOpen && (
                  <ul className="space-y-2 border-t border-gray-100 px-3 py-3 dark:border-gray-700">
                    {items.map((it, idx) => (
                      <li
                        key={`${it.title}-${idx}`}
                        className="rounded-md border border-white bg-white px-3 py-2 shadow-sm dark:border-gray-600 dark:bg-gray-900"
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ${insightSeverityClass(it.severity)}`}
                          >
                            {it.severity}
                          </span>
                          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{it.title}</span>
                        </div>
                        <p className="mt-1 text-xs leading-relaxed text-gray-600 dark:text-gray-400">{it.description}</p>
                        {it.entities.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {it.entities.map((e) => (
                              <code
                                key={e}
                                className="max-w-full truncate rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-800 dark:bg-gray-800 dark:text-gray-200"
                              >
                                {e}
                              </code>
                            ))}
                          </div>
                        )}
                        {it.suggestion && (
                          <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">{it.suggestion}</p>
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
