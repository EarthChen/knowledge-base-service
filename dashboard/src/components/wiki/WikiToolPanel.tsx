import { lazy, Suspense, type ReactNode } from "react";
import { useI18n } from "../../i18n/context";
import type { UseQueryResult } from "@tanstack/react-query";
import type { WikiPageDetail } from "../../hooks/wikiTypes";
import ErrorBoundary from "../ErrorBoundary";
import AskPanel from "./AskPanel";
import WikiContent from "./WikiContent";
import WikiCoverageCard from "./WikiCoverageCard";
import WikiQualityScoreCard from "./WikiQualityScoreCard";
import WikiLandingPage from "./WikiLandingPage";

const WikiReferenceGraph = lazy(() => import("./WikiReferenceGraph"));
const GraphInsightsPanel = lazy(() => import("./GraphInsightsPanel"));
const WikiBusinessExportPanel = lazy(() => import("./WikiBusinessExportPanel"));
const WikiLintPanel = lazy(() => import("./WikiLintPanel"));
const DeepResearchPanel = lazy(() => import("./DeepResearchPanel"));
const WikiBusinessFlowGraph = lazy(() => import("./WikiBusinessFlowGraph"));

export type WikiToolTab =
  | "page"
  | "coverage"
  | "export"
  | "health"
  | "insights"
  | "refgraph"
  | "research"
  | "flows";

/** Used as Suspense fallback for lazy wiki tool panels. Exported for i18n tests. */
export function WikiToolSuspenseFallback() {
  const { t } = useI18n();
  return (
    <div className="animate-pulse rounded-xl border p-8 text-center text-sm text-gray-400">{t.common.loading}</div>
  );
}

type ViewType = "business_domain" | "code_structure" | (string & {});

type Props = {
  toolTab: WikiToolTab;
  businessId: string;
  viewType: ViewType;
  pagePath: string;
  pageQuery: UseQueryResult<WikiPageDetail | null>;
  contentError: Error | null;
  wikiLinkParams: Record<string, string>;
  onAskQuestion?: (question: string) => void;
};

function panelBoundary(children: ReactNode) {
  return <ErrorBoundary fallbackLabel="Wiki tool panel failed to render">{children}</ErrorBoundary>;
}

export default function WikiToolPanel({
  toolTab,
  businessId,
  viewType,
  pagePath,
  pageQuery,
  contentError,
  wikiLinkParams,
  onAskQuestion,
}: Props) {
  return (
    <>
      {toolTab === "page" && !pagePath && (
        <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
          {panelBoundary(<WikiLandingPage businessId={businessId} viewType={viewType} />)}
        </div>
      )}

      {toolTab === "page" && pagePath && (
        <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
          {panelBoundary(
            <>
              <WikiContent
                repository={pageQuery.data?.context?.repository ?? businessId}
                businessId={businessId}
                pagePath={pagePath}
                detail={pageQuery.data}
                isLoading={pageQuery.isLoading}
                error={contentError}
                wikiLinkParams={wikiLinkParams}
                onAskQuestion={onAskQuestion}
              />
              <AskPanel repository={businessId} />
            </>,
          )}
        </div>
      )}

      {toolTab === "coverage" && (
        <div role="tabpanel" id="wiki-panel-coverage" aria-labelledby="wiki-tab-coverage">
          {panelBoundary(
            <div className="grid gap-4 lg:grid-cols-2">
              <WikiCoverageCard businessId={businessId} />
              <WikiQualityScoreCard businessId={businessId} />
            </div>,
          )}
        </div>
      )}

      {toolTab === "refgraph" && (
        <div role="tabpanel" id="wiki-panel-refgraph" aria-labelledby="wiki-tab-refgraph">
          {panelBoundary(
            <Suspense fallback={<WikiToolSuspenseFallback />}>
              <WikiReferenceGraph
                businessId={businessId}
                view={viewType === "code_structure" ? "code_structure" : "business_domain"}
              />
            </Suspense>,
          )}
        </div>
      )}

      {toolTab === "health" && (
        <div role="tabpanel" id="wiki-panel-health" aria-labelledby="wiki-tab-health">
          {panelBoundary(
            <Suspense fallback={<WikiToolSuspenseFallback />}>
              <WikiLintPanel repository={pageQuery.data?.context?.repository ?? businessId} />
            </Suspense>,
          )}
        </div>
      )}

      {toolTab === "insights" && (
        <div role="tabpanel" id="wiki-panel-insights" aria-labelledby="wiki-tab-insights">
          {panelBoundary(
            <Suspense fallback={<WikiToolSuspenseFallback />}>
              <GraphInsightsPanel repository={pageQuery.data?.context?.repository ?? businessId} />
            </Suspense>,
          )}
        </div>
      )}

      {toolTab === "export" && (
        <div role="tabpanel" id="wiki-panel-export" aria-labelledby="wiki-tab-export">
          {panelBoundary(
            <Suspense fallback={<WikiToolSuspenseFallback />}>
              <WikiBusinessExportPanel key={businessId} />
            </Suspense>,
          )}
        </div>
      )}

      {toolTab === "research" && (
        <div role="tabpanel" id="wiki-panel-research" aria-labelledby="wiki-tab-research">
          {panelBoundary(
            <Suspense fallback={<WikiToolSuspenseFallback />}>
              <DeepResearchPanel
                businessId={businessId}
                repository={pageQuery.data?.context?.repository ?? businessId}
              />
            </Suspense>,
          )}
        </div>
      )}

      {toolTab === "flows" && (
        <div role="tabpanel" id="wiki-panel-flows" aria-labelledby="wiki-tab-flows">
          {panelBoundary(
            <Suspense fallback={<WikiToolSuspenseFallback />}>
              <WikiBusinessFlowGraph businessId={businessId} />
            </Suspense>,
          )}
        </div>
      )}
    </>
  );
}
