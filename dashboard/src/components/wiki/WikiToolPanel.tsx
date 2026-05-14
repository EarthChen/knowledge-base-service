import { lazy, Suspense, useCallback, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useI18n } from "../../i18n/context";
import type { UseQueryResult } from "@tanstack/react-query";
import type { WikiPageDetail } from "../../hooks/wikiTypes";
import { useWikiDocumentationQualitySummary } from "../../hooks/useWikiQualityScore";
import { useWikiDomainTree, useWikiDomainEdges, type TopicTreeNode } from "../../hooks/useWikiDomainTree";
import { useBatchReview, useSetPageReview, useRegeneratePage } from "../../hooks/useWikiReview";
import ErrorBoundary from "../ErrorBoundary";
import WikiAssistantPanel from "./WikiAssistantPanel";
import WikiContent from "./WikiContent";
import WikiTopicContent from "./WikiTopicContent";
import WikiCoverageCard from "./WikiCoverageCard";
import WikiQualityScoreCard from "./WikiQualityScoreCard";
import WikiQualitySummary from "./WikiQualitySummary";
import WikiLandingPage from "./WikiLandingPage";
import WikiDomainReviewPanel from "./WikiDomainReviewPanel";
import WikiKnowledgeGraph from "./WikiKnowledgeGraph";

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
  | "flows"
  | "knowledge_graph";

/** Used as Suspense fallback for lazy wiki tool panels. Exported for i18n tests. */
export function WikiToolSuspenseFallback() {
  const { t } = useI18n();
  return (
    <div className="animate-pulse rounded-xl border p-8 text-center text-sm text-gray-400">{t.common.loading}</div>
  );
}

type ViewType = "business_domain" | "code_structure";

type WikiTier = "standard" | "essential" | "comprehensive" | null;

type Props = {
  toolTab: WikiToolTab;
  businessId: string;
  viewType: ViewType;
  wikiTier: WikiTier;
  pagePath: string;
  pageQuery: UseQueryResult<WikiPageDetail | null>;
  contentError: Error | null;
  wikiLinkParams: Record<string, string>;
  onAskQuestion?: (question: string) => void;
};

function mapTopicTreeToDomainPanelNodes(nodes: TopicTreeNode[]): {
  name: string;
  description?: string;
  modules: string[];
  moduleCount?: number;
  children: ReturnType<typeof mapTopicTreeToDomainPanelNodes>;
}[] {
  return nodes.map((n) => ({
    name: n.name,
    description: n.description,
    modules: [],
    moduleCount: n.module_count,
    children: mapTopicTreeToDomainPanelNodes(n.children ?? []),
  }));
}

function findTopicPathByName(nodes: TopicTreeNode[], name: string): string | null {
  for (const n of nodes) {
    if (n.name === name) return n.path;
    const nested = findTopicPathByName(n.children ?? [], name);
    if (nested) return nested;
  }
  return null;
}

function collectDomainApprovalReviews(
  nodes: TopicTreeNode[],
): Array<{ page_path: string; status: string }> {
  const reviews: Array<{ page_path: string; status: string }> = [];
  for (const node of nodes) {
    const page_path = node.path?.trim() || node.name;
    if (page_path) reviews.push({ page_path, status: "approved" });
    if (node.children?.length) reviews.push(...collectDomainApprovalReviews(node.children));
  }
  return reviews;
}

export default function WikiToolPanel({
  toolTab,
  businessId,
  viewType,
  wikiTier,
  pagePath,
  pageQuery,
  contentError,
  wikiLinkParams,
  onAskQuestion,
}: Props) {
  const { t } = useI18n();
  const panelBoundary = (children: ReactNode) => (
    <ErrorBoundary fallbackLabel={t.wiki.error_boundary.tool_panel_failed}>{children}</ErrorBoundary>
  );
  const dr = t.wiki.domain_review;
  const [, setSearchParams] = useSearchParams();
  const [domainReviewOpen, setDomainReviewOpen] = useState(false);
  const domainTreeQuery = useWikiDomainTree(businessId);
  const domainEdgesQuery = useWikiDomainEdges(businessId);
  const setPageReview = useSetPageReview();
  const regeneratePage = useRegeneratePage();
  const batchReview = useBatchReview();

  const docQualityRepo =
    pageQuery.data?.context?.repository?.trim() || businessId.trim();
  const docQualitySummary = useWikiDocumentationQualitySummary(docQualityRepo, toolTab === "coverage");

  const pageType = pageQuery.data?.context?.page_type?.trim() ?? "";
  const useTopicLayout = useMemo(
    () => ["topic", "domain_overview", "system_overview"].includes(pageType),
    [pageType],
  );

  const pendingDomainReview = domainTreeQuery.data?.review_status?.domain_tree === "pending_review";

  const handleKnowledgeGraphNodeClick = useCallback(
    (domainId: string) => {
      const tree = domainTreeQuery.data?.tree ?? [];
      const path = findTopicPathByName(tree, domainId);
      if (!path) return;
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("path", path);
          next.delete("tool");
          return next;
        },
        { replace: true },
      );
    },
    [domainTreeQuery.data?.tree, setSearchParams],
  );

  const domainGraphDomains = useMemo(
    () =>
      (domainTreeQuery.data?.tree ?? []).map((d) => ({
        id: d.name,
        label: d.name,
        children: [] as string[],
      })),
    [domainTreeQuery.data?.tree],
  );

  const knowledgeGraphLoading = domainTreeQuery.isLoading || domainEdgesQuery.isLoading;
  const knowledgeGraphError =
    domainTreeQuery.isError || domainEdgesQuery.isError
      ? (domainTreeQuery.error ?? domainEdgesQuery.error)
      : null;

  return (
    <>
      {pendingDomainReview && !domainReviewOpen && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
          <span>{dr.pending_review_banner}</span>
          <button
            type="button"
            onClick={() => setDomainReviewOpen(true)}
            className="font-medium text-sky-700 underline decoration-sky-600/60 hover:text-sky-800 dark:text-sky-400 dark:hover:text-sky-300"
          >
            {dr.expand_review}
          </button>
        </div>
      )}

      {pendingDomainReview && domainReviewOpen && (
        <div className="mb-4 space-y-2">
          <button
            type="button"
            onClick={() => setDomainReviewOpen(false)}
            className="text-xs font-medium text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
          >
            {dr.collapse_review}
          </button>
          {panelBoundary(
            <WikiDomainReviewPanel
              domainTree={mapTopicTreeToDomainPanelNodes(domainTreeQuery.data?.tree ?? [])}
              reviewStatus={domainTreeQuery.data?.review_status ?? {}}
              isPending={batchReview.isPending}
              onApprove={() => {
                const tree = domainTreeQuery.data?.tree ?? [];
                const reviews = collectDomainApprovalReviews(tree);
                if (reviews.length > 0) {
                  batchReview.mutate(
                    { businessId, reviews },
                    { onSuccess: () => setDomainReviewOpen(false) },
                  );
                }
              }}
            />,
          )}
        </div>
      )}

      {toolTab === "page" && !pagePath && (
        <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
          {panelBoundary(<WikiLandingPage businessId={businessId} viewType={viewType} wikiTier={wikiTier} />)}
        </div>
      )}

      {toolTab === "page" && pagePath && (
        <div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
          {panelBoundary(
            <>
              {useTopicLayout && pageQuery.data ? (
                <WikiTopicContent
                  page={{
                    title: pageQuery.data.title,
                    content: pageQuery.data.content,
                    path: pageQuery.data.path || pagePath,
                    page_type: pageType,
                    domain: pageQuery.data.context?.business_domain,
                    review_status: pageQuery.data.context?.review_status,
                    source_locations: pageQuery.data.source_locations,
                  }}
                  businessId={businessId}
                  repository={pageQuery.data.context?.repository?.trim() || businessId}
                  wikiLinkParams={wikiLinkParams}
                  onReviewAction={(action, notes) => {
                    if (action === "approve") {
                      setPageReview.mutate({ pagePath, status: "approved", notes: "" });
                    } else if (action === "needs_revision") {
                      setPageReview.mutate({
                        pagePath,
                        status: "needs_revision",
                        notes: notes ?? "",
                      });
                    } else {
                      regeneratePage.mutate({ pagePath });
                    }
                  }}
                />
              ) : (
                <WikiContent
                  repository={pageQuery.data?.context?.repository ?? businessId}
                  businessId={businessId}
                  pagePath={pagePath}
                  detail={pageQuery.data ?? undefined}
                  isLoading={pageQuery.isLoading}
                  error={contentError}
                  wikiLinkParams={wikiLinkParams}
                  onAskQuestion={onAskQuestion}
                />
              )}
              <WikiAssistantPanel
                pageUid={(pageQuery.data?.context?.uid ?? pageQuery.data?.path ?? pagePath)?.trim() || ""}
                currentContent={pageQuery.data?.content ?? ""}
                businessId={businessId}
                repository={pageQuery.data?.context?.repository?.trim() || businessId.trim()}
                pageContext={
                  pageQuery.data?.content
                    ? `[Current page: ${pageQuery.data?.title}]\n${pageQuery.data?.content?.slice(0, 2000)}`
                    : undefined
                }
                onContentApplied={() => {
                  void pageQuery.refetch();
                }}
              />
            </>,
          )}
        </div>
      )}

      {toolTab === "coverage" && (
        <div role="tabpanel" id="wiki-panel-coverage" aria-labelledby="wiki-tab-coverage">
          {panelBoundary(
            <div className="space-y-4">
              <WikiQualitySummary
                summary={docQualitySummary.data ?? undefined}
                isLoading={docQualitySummary.isLoading}
              />
              <div className="grid gap-4 lg:grid-cols-2">
                <WikiCoverageCard businessId={businessId} />
                <WikiQualityScoreCard businessId={businessId} />
              </div>
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
              <WikiBusinessExportPanel
                key={businessId}
                repository={pageQuery.data?.context?.repository ?? businessId}
                businessId={businessId}
              />
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

      {toolTab === "knowledge_graph" && (
        <div role="tabpanel" id="wiki-panel-knowledge_graph" aria-labelledby="wiki-tab-knowledge_graph">
          {panelBoundary(
            <WikiKnowledgeGraph
              domains={domainGraphDomains}
              domainEdges={domainEdgesQuery.data?.edges ?? []}
              onNodeClick={handleKnowledgeGraphNodeClick}
              isLoading={knowledgeGraphLoading}
              error={knowledgeGraphError}
            />,
          )}
        </div>
      )}

    </>
  );
}
