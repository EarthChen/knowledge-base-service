import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import WikiToolPanel from "../WikiToolPanel";
import type { WikiPageDetail } from "../../../hooks/wikiTypes";
import { renderWithI18n } from "../../../test/renderWithI18n";

vi.mock("../WikiLandingPage", () => ({
  default: () => <div data-testid="wiki-landing-mock">landing</div>,
}));

vi.mock("../WikiAssistantPanel", () => ({
  default: () => <div data-testid="ask-spy" />,
}));

vi.mock("../WikiContent", () => ({
  default: () => <div data-testid="wiki-content-mock">content</div>,
}));

vi.mock("../WikiTopicContent", () => ({
  default: () => <div data-testid="wiki-topic-mock">topic</div>,
}));

vi.mock("../WikiQualitySummary", () => ({
  default: () => <div data-testid="wiki-quality-summary-mock" />,
}));

vi.mock("../WikiCoverageCard", () => ({
  default: () => <div data-testid="wiki-coverage-mock" />,
}));

vi.mock("../WikiQualityScoreCard", () => ({
  default: () => <div data-testid="wiki-quality-score-mock" />,
}));

vi.mock("../../../hooks/useWikiDomainTree", () => ({
  useWikiDomainTree: vi.fn(() => ({
    data: {
      tree: [{ name: "Domain A", path: "wiki/domain-a", children: [], module_count: 2 }],
      review_status: { domain_tree: "approved" as const },
    },
    isLoading: false,
    isError: false,
  })),
  useWikiDomainEdges: vi.fn(() => ({
    data: { edges: [] },
    isLoading: false,
    isError: false,
  })),
}));

vi.mock("../../../hooks/useWikiQualityScore", () => ({
  useWikiDocumentationQualitySummary: () => ({ data: undefined, isLoading: false }),
}));

vi.mock("../../../hooks/useWikiReview", () => ({
  useSetPageReview: () => ({ mutate: vi.fn(), isPending: false }),
  useRegeneratePage: () => ({ mutate: vi.fn(), isPending: false }),
  useBatchReview: () => ({ mutate: vi.fn(), isPending: false }),
}));

let knowledgeGraphReady = false;
let resolveKnowledgeGraph: (() => void) | undefined;

vi.mock("../WikiKnowledgeGraph", () => ({
  default: function WikiKnowledgeGraphLazyMock() {
    if (!knowledgeGraphReady) {
      throw new Promise<void>((resolve) => {
        resolveKnowledgeGraph = () => {
          knowledgeGraphReady = true;
          resolve();
        };
      });
    }
    return <div data-testid="wiki-knowledge-graph-loaded">graph</div>;
  },
}));

function makePageQuery(data: WikiPageDetail | null): UseQueryResult<WikiPageDetail | null> {
  return {
    data,
    isLoading: false,
    isError: false,
    error: null,
    isPending: false,
    isLoadingError: false,
    refetch: vi.fn(),
  } as UseQueryResult<WikiPageDetail | null>;
}

function renderPanel(toolTab: "page" | "knowledge_graph") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiToolPanel
          toolTab={toolTab}
          businessId="business-1"
          viewType="business_domain"
          wikiTier={null}
          pagePath=""
          pageQuery={makePageQuery(null)}
          contentError={null}
          wikiLinkParams={{}}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WikiToolPanel lazy loading", () => {
  beforeEach(() => {
    knowledgeGraphReady = false;
    resolveKnowledgeGraph = undefined;
    vi.clearAllMocks();
  });

  it("renders without errors on page tab", () => {
    renderPanel("page");
    expect(screen.getByTestId("wiki-landing-mock")).toBeInTheDocument();
  });

  it("shows suspense loading state when knowledge graph tab is selected", () => {
    renderPanel("knowledge_graph");
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByTestId("wiki-knowledge-graph-loaded")).not.toBeInTheDocument();
  });
});
