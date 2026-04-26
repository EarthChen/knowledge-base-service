import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import ErrorBoundary from "../ErrorBoundary";
import {
  Activity,
  FileOutput,
  GitBranch,
  LayoutGrid,
  Loader2,
  Network,
  PieChart,
  RefreshCw,
} from "lucide-react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import AskPanel from "./AskPanel";
import WikiContent from "./WikiContent";
import WikiReferencesPanel from "./WikiReferencesPanel";
import WikiCoverageCard from "./WikiCoverageCard";
import WikiQualityScoreCard from "./WikiQualityScoreCard";
import WikiLandingPage from "./WikiLandingPage";
import WikiSearchBar from "./WikiSearchBar";
import WikiTreeNav from "./WikiTreeNav";
import { parseWikiSearchParams, wikiSearchHref } from "./wikiRouteHelpers";
import { useBusiness } from "../../contexts/BusinessContext";
import { useI18n } from "../../i18n/context";
import type { WikiEvent, WikiEventType } from "../../hooks/wikiTypes";
import { useWikiEvents } from "../../hooks/useWikiEvents";
import { useWikiPageByPath } from "../../hooks/useWikiPageByPath";
import { useWikiRegenerate } from "../../hooks/useWikiRegenerate";
import WikiGenerationProgress from "./WikiGenerationProgress";
import WikiUpdateNotification from "./WikiUpdateNotification";

const WikiReferenceGraph = lazy(() => import("./WikiReferenceGraph"));
const GraphInsightsPanel = lazy(() => import("./GraphInsightsPanel"));
const WikiBusinessExportPanel = lazy(() => import("./WikiBusinessExportPanel"));
const WikiLintPanel = lazy(() => import("./WikiLintPanel"));

const wikiToolSuspenseFallback = (
  <div className="animate-pulse rounded-xl border p-8 text-center text-sm text-gray-400">Loading...</div>
);

/** All wiki query keys use `["wiki", <segment>, businessId, ...]` — invalidate everything for this business. */
function invalidateWikiQueriesForBusiness(queryClient: QueryClient, businessId: string) {
  const b = businessId.trim();
  if (!b) return Promise.resolve();
  return queryClient.invalidateQueries({
    predicate: (q) => {
      const k = q.queryKey as unknown[];
      return k[0] === "wiki" && k[2] === b;
    },
  });
}

type WikiToolTab = "page" | "coverage" | "export" | "health" | "insights" | "refgraph";

export default function WikiShell() {
  const [searchParams, setSearchParams] = useSearchParams();
  const parsed = useMemo(() => parseWikiSearchParams(searchParams), [searchParams]);
  const { currentBusiness } = useBusiness();
  const businessId = parsed.businessId?.trim() || currentBusiness;

  const pagePath = parsed.path?.trim() ?? "";
  const viewType = parsed.viewType;
  const toolTab = parsed.toolTab;

  const focusAsk = searchParams.get("focus");
  useEffect(() => {
    if (focusAsk !== "ask") return;
    const id = window.setTimeout(() => {
      document.getElementById("wiki-ask-panel")?.scrollIntoView({ behavior: "smooth", block: "start" });
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("focus");
          return next;
        },
        { replace: true },
      );
    }, 0);
    return () => window.clearTimeout(id);
  }, [focusAsk, setSearchParams]);

  const wikiLinkParams = useMemo(
    () =>
      ({
        business_id: businessId,
        view: viewType,
      }) as Record<string, string>,
    [businessId, viewType],
  );

  const pageQuery = useWikiPageByPath(businessId, pagePath || undefined);
  const queryClient = useQueryClient();
  const { t } = useI18n();
  const { regenerate: handleRegenerateWiki, isPending: regeneratePending } = useWikiRegenerate(businessId);
  const [updateNotification, setUpdateNotification] = useState<string | null>(null);
  const [generationStatus, setGenerationStatus] = useState<WikiEventType | null>(null);
  const [refsPanelOpen, setRefsPanelOpen] = useState(() => {
    try {
      return localStorage.getItem("kb_wiki_refs_panel") !== "closed";
    } catch {
      return true;
    }
  });

  const toggleRefsPanel = useCallback(() => {
    setRefsPanelOpen((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("kb_wiki_refs_panel", next ? "open" : "closed");
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const handleWikiEvent = useCallback(
    (event: WikiEvent) => {
      if (event.type === "wiki:page_updated" && event.page_path) {
        setUpdateNotification(event.page_path);
      } else if (
        event.type === "wiki:generation_started" ||
        event.type === "wiki:generation_completed" ||
        event.type === "wiki:generation_failed"
      ) {
        setGenerationStatus(event.type);
        if (event.type === "wiki:generation_completed") {
          void invalidateWikiQueriesForBusiness(queryClient, businessId);
        }
      }
    },
    [queryClient, businessId],
  );

  useWikiEvents(businessId.trim(), handleWikiEvent);

  const setViewType = useCallback(
    (v: typeof viewType) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (v === "business_domain") next.delete("view");
          else next.set("view", v);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const pendingQuery = searchParams.get("q") ?? "";
  if (pendingQuery.trim()) {
    return <Navigate to={wikiSearchHref(pendingQuery.trim())} replace />;
  }

  const setToolTab = useCallback(
    (tab: WikiToolTab) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (tab === "page") next.delete("tool");
          else next.set("tool", tab);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  const contentError =
    pagePath && pageQuery.isError
      ? pageQuery.error instanceof Error
        ? pageQuery.error
        : new Error(String(pageQuery.error))
      : null;

  const tabBtn = useCallback(
    (id: WikiToolTab, label: string, icon: ReactNode) => (
      <button
        key={id}
        type="button"
        role="tab"
        id={`wiki-tab-${id}`}
        aria-selected={toolTab === id}
        aria-controls={`wiki-panel-${id}`}
        onClick={() => setToolTab(id)}
        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors ${
          toolTab === id
            ? "bg-sky-100 text-sky-800 ring-1 ring-sky-200 dark:bg-sky-950 dark:text-sky-200 dark:ring-sky-800"
            : "text-gray-600 hover:bg-gray-100 hover:text-gray-900 dark:text-gray-400 dark:hover:bg-gray-800 dark:hover:text-gray-100"
        }`}
      >
        {icon}
        {label}
      </button>
    ),
    [setToolTab, toolTab],
  );

  return (
    <ErrorBoundary fallbackLabel="Wiki failed to render">
    <div className="flex min-h-[min(70vh,860px)] flex-col gap-4 lg:flex-row lg:items-stretch">
      <WikiTreeNav
        businessId={businessId}
        viewType={viewType}
        activePath={pagePath}
        onViewChange={setViewType}
      />

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
          <div className="flex flex-wrap gap-2" role="tablist" aria-label="Wiki tools">
            {tabBtn(
              "page",
              t.wiki.tabPage,
              <LayoutGrid size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />,
            )}
            {tabBtn(
              "coverage",
              t.wiki.coverageTitle,
              <PieChart size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />,
            )}
            {tabBtn(
              "health",
              t.wiki.tabHealth,
              <Activity size={14} className="text-emerald-600 dark:text-emerald-400" aria-hidden />,
            )}
            {tabBtn(
              "insights",
              t.wiki.tabInsights,
              <Network size={14} className="text-violet-600 dark:text-violet-400" aria-hidden />,
            )}
            {tabBtn(
              "refgraph",
              t.wiki.tabRefGraph,
              <GitBranch size={14} className="text-cyan-600 dark:text-cyan-400" aria-hidden />,
            )}
            {tabBtn(
              "export",
              t.wiki.tabExport,
              <FileOutput size={14} className="text-sky-600 dark:text-sky-400" aria-hidden />,
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <WikiSearchBar repository={businessId} linkParams={wikiLinkParams} />
            <button
              type="button"
              onClick={handleRegenerateWiki}
              disabled={regeneratePending}
              aria-busy={regeneratePending}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950"
            >
              {regeneratePending ? (
                <Loader2 size={14} className="animate-spin" aria-hidden />
              ) : (
                <RefreshCw size={14} aria-hidden />
              )}
              {t.wiki.regenerate}
            </button>
          </div>
        </div>

        {updateNotification && (
          <WikiUpdateNotification
            pagePath={updateNotification}
            onRefresh={() => {
              void invalidateWikiQueriesForBusiness(queryClient, businessId);
              setUpdateNotification(null);
            }}
            onDismiss={() => setUpdateNotification(null)}
          />
        )}
        <WikiGenerationProgress status={generationStatus} />

        {toolTab === "page" && !pagePath && (
          <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
            <WikiLandingPage businessId={businessId} viewType={viewType} />
          </div>
        )}

        {toolTab === "page" && pagePath && (
          <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
            <WikiContent
              repository={pageQuery.data?.context?.repository ?? businessId}
              businessId={businessId}
              pagePath={pagePath}
              detail={pageQuery.data}
              isLoading={pageQuery.isLoading}
              error={contentError}
              wikiLinkParams={wikiLinkParams}
              onAskQuestion={(q) => {
                const el = document.getElementById("wiki-ask-panel");
                if (el) {
                  el.scrollIntoView({ behavior: "smooth", block: "start" });
                  const input = el.querySelector<HTMLTextAreaElement>("textarea");
                  if (input) {
                    input.value = q;
                    input.dispatchEvent(new Event("input", { bubbles: true }));
                    input.focus();
                  }
                }
              }}
            />
            <AskPanel repository={businessId} />
          </div>
        )}

        {toolTab === "coverage" && (
          <div role="tabpanel" id="wiki-panel-coverage" aria-labelledby="wiki-tab-coverage">
            <div className="grid gap-4 lg:grid-cols-2">
              <WikiCoverageCard businessId={businessId} />
              <WikiQualityScoreCard businessId={businessId} />
            </div>
          </div>
        )}

        {toolTab === "refgraph" && (
          <div role="tabpanel" id="wiki-panel-refgraph" aria-labelledby="wiki-tab-refgraph">
            <Suspense fallback={wikiToolSuspenseFallback}>
              <WikiReferenceGraph
                businessId={businessId}
                view={viewType === "code_structure" ? "code_structure" : "business_domain"}
              />
            </Suspense>
          </div>
        )}

        {toolTab === "health" && (
          <div role="tabpanel" id="wiki-panel-health" aria-labelledby="wiki-tab-health">
            <Suspense fallback={wikiToolSuspenseFallback}>
              <WikiLintPanel repository={pageQuery.data?.context?.repository ?? businessId} />
            </Suspense>
          </div>
        )}

        {toolTab === "insights" && (
          <div role="tabpanel" id="wiki-panel-insights" aria-labelledby="wiki-tab-insights">
            <Suspense fallback={wikiToolSuspenseFallback}>
              <GraphInsightsPanel repository={pageQuery.data?.context?.repository ?? businessId} />
            </Suspense>
          </div>
        )}

        {toolTab === "export" && (
          <div role="tabpanel" id="wiki-panel-export" aria-labelledby="wiki-tab-export">
            <Suspense fallback={wikiToolSuspenseFallback}>
              <WikiBusinessExportPanel key={businessId} />
            </Suspense>
          </div>
        )}
      </div>

      {toolTab === "page" && pagePath && pageQuery.data && (
        <WikiReferencesPanel
          businessId={businessId}
          pageUid={pageQuery.data.context?.uid ?? ""}
          pagePath={pageQuery.data.path}
          repository={pageQuery.data.context?.repository ?? ""}
          wikiLinkParams={wikiLinkParams}
          isOpen={refsPanelOpen}
          onToggle={toggleRefsPanel}
        />
      )}
    </div>
    </ErrorBoundary>
  );
}
