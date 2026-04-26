import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronUp, GitMerge, Loader2 } from "lucide-react";
import type { WikiPageDetail } from "../../hooks/wikiTypes";
import { useAnalyzeImpact } from "../../api/hooks";
import type { AnalyzeImpactResponse } from "../../api/types";
import { getErrorMessage } from "../../utils/errorUtils";
import { useI18n } from "../../i18n/context";
import { wikiHref } from "./wikiRouteHelpers";

function chainCardClass(level: string): string {
  const l = level.toLowerCase();
  if (l.includes("high")) {
    return "border-red-200 bg-red-50/90 dark:border-red-900/50 dark:bg-red-950/40";
  }
  if (l.includes("medium")) {
    return "border-amber-200 bg-amber-50/90 dark:border-amber-900/50 dark:bg-amber-950/40";
  }
  if (l.includes("low")) {
    return "border-emerald-200 bg-emerald-50/90 dark:border-emerald-900/50 dark:bg-emerald-950/40";
  }
  return "border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800/80";
}

export default function CallChainSection({
  repository,
  detail,
  wikiLinkParams,
}: {
  repository: string;
  detail: WikiPageDetail;
  wikiLinkParams?: Record<string, string>;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);
  const analyzeMutation = useAnalyzeImpact();
  const [impactResult, setImpactResult] = useState<AnalyzeImpactResponse | null>(null);

  const fqns = useMemo(
    () => detail.source_locations.map((loc) => loc.fqn).filter(Boolean),
    [detail.source_locations],
  );

  const changedFiles = useMemo(() => {
    const map = new Map<string, { path: string; status: "modified" }>();
    for (const loc of detail.source_locations) {
      if (!loc.file_path) continue;
      map.set(loc.file_path, { path: loc.file_path, status: "modified" });
    }
    return Array.from(map.values());
  }, [detail.source_locations]);

  if (!detail.source_locations?.length) return null;

  const handleAnalyze = () => {
    setImpactResult(null);
    analyzeMutation.mutate(
      { repository, changed_files: changedFiles },
      {
        onSuccess: (data) => setImpactResult(data),
      },
    );
  };

  return (
    <section className="mt-10 border-t border-gray-100 pt-8 dark:border-gray-800">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between gap-3 rounded-lg px-1 py-2 text-left hover:bg-gray-50/80 dark:hover:bg-gray-800/60"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-gray-900 dark:text-gray-100">
          <GitMerge size={18} className="text-violet-600 dark:text-violet-400" aria-hidden />
          {t.wiki.callChainTitle}
        </span>
        {expanded ? (
          <ChevronUp size={18} className="text-gray-500 dark:text-gray-400" />
        ) : (
          <ChevronDown size={18} className="text-gray-500 dark:text-gray-400" />
        )}
      </button>

      {expanded && (
        <div className="mt-3 space-y-4 rounded-xl border border-gray-100 bg-gray-50/60 p-4 shadow-inner dark:border-gray-700 dark:bg-gray-800/40">
          <div>
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
              {t.wiki.callChainFqns}
            </h4>
            <ul className="flex flex-wrap gap-2">
              {fqns.map((fqn, i) => (
                <li key={`${fqn}-${i}`}>
                  <code className="rounded-md bg-white px-2 py-1 font-mono text-[11px] text-gray-800 ring-1 ring-gray-200/80 dark:bg-gray-900 dark:text-gray-200 dark:ring-gray-600">
                    {fqn}
                  </code>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={handleAnalyze}
              disabled={analyzeMutation.isPending || changedFiles.length === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-violet-500 disabled:opacity-50"
            >
              {analyzeMutation.isPending ? (
                <Loader2 className="size-4 animate-spin" aria-hidden />
              ) : (
                <GitMerge className="size-4" aria-hidden />
              )}
              {analyzeMutation.isPending ? t.wiki.callChainAnalyzing : t.wiki.callChainViewImpact}
            </button>
          </div>

          {analyzeMutation.isError && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/40 dark:text-red-300">
              {getErrorMessage(analyzeMutation.error, t.common.unexpectedError)}
            </div>
          )}

          {impactResult && (
            <div>
              <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
                {t.wiki.callChainAffectedPages}
              </h4>
              {impactResult.affected_pages?.length ? (
                <ul className="space-y-2">
                  {impactResult.affected_pages.map((p, i) => (
                    <li
                      key={`${p.wiki_page_path}-${i}`}
                      className={`rounded-lg border p-3 shadow-sm ${chainCardClass(p.impact_level)}`}
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <Link
                            to={wikiHref(p.wiki_page_path, wikiLinkParams)}
                            className="inline-block truncate font-mono text-sm font-medium text-sky-700 underline decoration-sky-200 dark:text-sky-400 dark:decoration-sky-800"
                          >
                            {p.wiki_page_path}
                          </Link>
                          {p.affected_entities.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {p.affected_entities.map((e) => (
                                <code
                                  key={e}
                                  className="rounded bg-white/80 px-1 py-0.5 text-xs text-gray-700 dark:bg-gray-800/90 dark:text-gray-300"
                                >
                                  {e}
                                </code>
                              ))}
                            </div>
                          )}
                        </div>
                        <span className="shrink-0 rounded-full bg-white/90 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-700 ring-1 ring-gray-200 dark:bg-gray-900/90 dark:text-gray-200 dark:ring-gray-600">
                          {t.wiki.callChainImpactLabel}: {p.impact_level}
                        </span>
                      </div>
                      {p.reason && (
                        <p className="mt-2 text-xs leading-relaxed text-gray-700 dark:text-gray-300">{p.reason}</p>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-gray-600 dark:text-gray-400">{t.wiki.callChainEmpty}</p>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
