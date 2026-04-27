import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { Navigate, useSearchParams } from "react-router-dom";
import ErrorBoundary from "../ErrorBoundary";
import { useQueryClient } from "@tanstack/react-query";
import WikiReferencesPanel from "./WikiReferencesPanel";
import { parseWikiSearchParams, wikiSearchHref } from "./wikiRouteHelpers";
import { useBusiness } from "../../contexts/BusinessContext";
import { useI18n } from "../../i18n/context";
import type { WikiEvent, WikiEventType } from "../../hooks/wikiTypes";
import { useWikiEvents } from "../../hooks/useWikiEvents";
import { useWikiPageByPath } from "../../hooks/useWikiPageByPath";
import { invalidateWikiQueriesForBusiness } from "../../hooks/invalidateWikiQueries";
import { useWikiRegenerate } from "../../hooks/useWikiRegenerate";
import WikiToolTabStrip from "./WikiToolTabStrip";
import WikiToolPanel, { type WikiToolTab, WikiToolSuspenseFallback } from "./WikiToolPanel";
import WikiSearchBar from "./WikiSearchBar";
import WikiGenerationProgress from "./WikiGenerationProgress";
import WikiUpdateNotification from "./WikiUpdateNotification";
import WikiTreeNav from "./WikiTreeNav";

export { WikiToolSuspenseFallback };

export default function WikiShell() {
  const [searchParams, setSearchParams] = useSearchParams();
  const parsed = useMemo(() => parseWikiSearchParams(searchParams), [searchParams]);
  const { currentBusiness } = useBusiness();
  const businessId = parsed.businessId?.trim() || currentBusiness;

  const pagePath = parsed.path?.trim() ?? "";
  const viewType = parsed.viewType;
  const toolTab = parsed.toolTab;
  const wikiTier = parsed.wikiTier;

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

  const wikiLinkParams = useMemo(() => {
    const p: Record<string, string> = {
      business_id: businessId,
      view: viewType,
    };
    if (wikiTier) p.wiki_tier = wikiTier;
    return p;
  }, [businessId, viewType, wikiTier]);

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

  const setWikiTier = useCallback(
    (tier: string | null) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (tier) next.set("wiki_tier", tier);
          else next.delete("wiki_tier");
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

  return (
    <ErrorBoundary fallbackLabel="Wiki failed to render">
      <div className="flex min-h-[min(70vh,860px)] flex-col gap-4 lg:flex-row lg:items-stretch">
        <WikiTreeNav
          businessId={businessId}
          viewType={viewType}
          activePath={pagePath}
          onViewChange={setViewType}
          wikiTier={wikiTier}
          onWikiTierChange={setWikiTier}
        />

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gray-200 bg-white px-3 py-2 shadow-sm dark:border-gray-700 dark:bg-gray-900">
            <WikiToolTabStrip toolTab={toolTab} onToolTabChange={setToolTab} />
            <div className="flex flex-wrap items-center gap-2">
              <WikiSearchBar repository={businessId} linkParams={wikiLinkParams} />
              <button
                type="button"
                onClick={handleRegenerateWiki}
                disabled={regeneratePending}
                aria-busy={regeneratePending}
                className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-900 hover:bg-amber-100 disabled:opacity-50 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200 dark:hover:bg-amber-950"
              >
                {regeneratePending ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <RefreshCw size={14} aria-hidden />}
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

          <WikiToolPanel
            toolTab={toolTab}
            businessId={businessId}
            viewType={viewType}
            wikiTier={wikiTier}
            pagePath={pagePath}
            pageQuery={pageQuery}
            contentError={contentError}
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
