import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
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
import { useQueryClient } from "@tanstack/react-query";
import AskPanel from "./AskPanel";
import GraphInsightsPanel from "./GraphInsightsPanel";
import WikiContent from "./WikiContent";
import WikiReferencesPanel from "./WikiReferencesPanel";
import WikiCoverageCard from "./WikiCoverageCard";
import WikiQualityScoreCard from "./WikiQualityScoreCard";
import WikiReferenceGraph from "./WikiReferenceGraph";
import WikiBusinessExportPanel from "./WikiBusinessExportPanel";
import WikiLandingPage from "./WikiLandingPage";
import WikiLintPanel from "./WikiLintPanel";
import { getErrorMessage } from "../../utils/errorUtils";
import WikiSearchBar from "./WikiSearchBar";
import WikiTreeNav from "./WikiTreeNav";
import { parseWikiSearchParams, wikiSearchHref } from "./wikiRouteHelpers";
import { businessWikiGenerate, wikiTaskStatus } from "../../api/client";
import { useToast } from "../Toast";
import { useBusiness } from "../../contexts/BusinessContext";
import { useI18n } from "../../i18n/context";
import type { WikiEvent, WikiEventType } from "../../hooks/wikiTypes";
import { useWikiEvents } from "../../hooks/useWikiEvents";
import { useWikiPageByPath } from "../../hooks/useWikiPageByPath";
import WikiGenerationProgress from "./WikiGenerationProgress";
import WikiUpdateNotification from "./WikiUpdateNotification";

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
  const { toast } = useToast();
  const { locale, t } = useI18n();
  const [updateNotification, setUpdateNotification] = useState<string | null>(null);
  const [generationStatus, setGenerationStatus] = useState<WikiEventType | null>(null);
  const [regeneratePending, setRegeneratePending] = useState(false);
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
          queryClient.invalidateQueries({ queryKey: ["wiki"] });
        }
      }
    },
    [queryClient],
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

  async function handleRegenerateWiki() {
    if (!businessId.trim() || regeneratePending) return;
    setRegeneratePending(true);
    try {
      const lang = locale === "zh" ? "zh" : "en";
      const res = await businessWikiGenerate(businessId.trim(), lang);
      const tid = res.task_id ? String(res.task_id) : "";
      if (!tid) {
        toast("success", t.wiki.regenerateStarted);
        await queryClient.invalidateQueries({ queryKey: ["wiki"] });
        return;
      }
      toast("info", t.wiki.regenerateRunning);
      const maxAttempts = 45;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const st = await wikiTaskStatus(tid);
        if (st.status === "completed") {
          toast("success", t.wiki.regenerateComplete);
          await queryClient.invalidateQueries({ queryKey: ["wiki"] });
          return;
        }
        if (st.status === "failed") {
          const err = st.error;
          const detail =
            err && typeof err === "object" && "detail" in err
              ? String((err as { detail?: unknown }).detail ?? err)
              : err
                ? JSON.stringify(err)
                : t.common.unknown;
          toast("error", t.wiki.regenerateFailed.replace("{detail}", detail));
          return;
        }
      }
      toast("error", t.wiki.regenerateTimeout);
    } catch (e) {
      toast("error", getErrorMessage(e, t.common.unexpectedError));
    } finally {
      setRegeneratePending(false);
    }
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
          <div className="flex flex-wrap gap-2">
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
              queryClient.invalidateQueries({ queryKey: ["wiki"] });
              setUpdateNotification(null);
            }}
            onDismiss={() => setUpdateNotification(null)}
          />
        )}
        <WikiGenerationProgress status={generationStatus} />

        {toolTab === "page" && !pagePath && (
          <WikiLandingPage businessId={businessId} viewType={viewType} />
        )}

        {toolTab === "page" && pagePath && (
          <>
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
          </>
        )}

        {toolTab === "coverage" && (
          <div className="grid gap-4 lg:grid-cols-2">
            <WikiCoverageCard businessId={businessId} />
            <WikiQualityScoreCard businessId={businessId} />
          </div>
        )}

        {toolTab === "refgraph" && (
          <WikiReferenceGraph
            businessId={businessId}
            view={viewType === "code_structure" ? "code_structure" : "business_domain"}
          />
        )}

        {toolTab === "health" && (
          <WikiLintPanel repository={pageQuery.data?.context?.repository ?? businessId} />
        )}

        {toolTab === "insights" && (
          <GraphInsightsPanel repository={pageQuery.data?.context?.repository ?? businessId} />
        )}

        {toolTab === "export" && <WikiBusinessExportPanel key={businessId} />}
      </div>

      {toolTab === "page" && pagePath && pageQuery.data && (
        <WikiReferencesPanel
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
