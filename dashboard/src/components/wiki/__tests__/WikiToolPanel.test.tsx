import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { UseQueryResult } from "@tanstack/react-query";
import WikiToolPanel from "../WikiToolPanel";
import type { WikiPageDetail } from "../../../hooks/wikiTypes";
import { renderWithI18n } from "../../../test/renderWithI18n";

const landingCtrl = vi.hoisted(() => ({ shouldThrow: false }));

const AskPanelSpy = vi.hoisted(() =>
  vi.fn((props: { repository?: string; pageContext?: string }) => (
    <div
      data-testid="ask-spy"
      data-repository={props.repository ?? ""}
      data-page-context={props.pageContext ?? ""}
    />
  )),
);

vi.mock("../WikiLandingPage", () => ({
  default: () => {
    if (landingCtrl.shouldThrow) throw new Error("WikiLandingPage blew up");
    return <div data-testid="wiki-landing-mock">landing</div>;
  },
}));

vi.mock("../WikiAssistantPanel", () => ({
  default: (props: { repository?: string; pageContext?: string }) => AskPanelSpy(props),
}));

vi.mock("../WikiDomainReviewPanel", () => ({
  default: () => <div data-testid="wiki-domain-review-mock">domain-review</div>,
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

vi.mock("../WikiKnowledgeGraph", () => ({
  default: () => <div data-testid="wiki-knowledge-graph-mock" />,
}));

vi.mock("../../../hooks/useWikiDomainTree", () => ({
  useWikiDomainTree: vi.fn(() => ({
    data: {
      tree: [{ name: "Domain A", path: "wiki/domain-a", children: [], module_count: 2 }],
      review_status: { domain_tree: "pending_review" as const },
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

function makePageQuery(
  data: WikiPageDetail | null,
): UseQueryResult<WikiPageDetail | null> {
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

function renderPanel(
  toolTab: Parameters<typeof WikiToolPanel>[0]["toolTab"],
  opts: Partial<Parameters<typeof WikiToolPanel>[0]> = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const pageQuery = opts.pageQuery ?? makePageQuery(null);
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiToolPanel
          toolTab={toolTab}
          businessId={opts.businessId ?? "business-1"}
          viewType={opts.viewType ?? "business_domain"}
          wikiTier={opts.wikiTier ?? null}
          pagePath={opts.pagePath ?? ""}
          pageQuery={pageQuery}
          contentError={opts.contentError ?? null}
          wikiLinkParams={opts.wikiLinkParams ?? {}}
          onAskQuestion={opts.onAskQuestion}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("WikiToolPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    landingCtrl.shouldThrow = false;
  });

  it("renders without crashing with minimal props (landing, no path)", () => {
    renderPanel("page", { pagePath: "" });
    expect(screen.getByTestId("wiki-landing-mock")).toBeInTheDocument();
  });

  it("shows page tabpanel when toolTab is page (landing)", () => {
    const { container } = renderPanel("page", { pagePath: "" });
    expect(container.querySelector("#wiki-panel-page")).not.toBeNull();
    expect(container.querySelector("#wiki-panel-coverage")).toBeNull();
  });

  it("shows coverage tabpanel when toolTab is coverage", () => {
    const { container } = renderPanel("coverage", { pagePath: "" });
    expect(container.querySelector("#wiki-panel-coverage")).not.toBeNull();
    expect(container.querySelector("#wiki-panel-page")).toBeNull();
    expect(screen.getByTestId("wiki-quality-summary-mock")).toBeInTheDocument();
  });

  it("passes trimmed repository from page context to WikiAssistantPanel / Ask branch (BUG-F1)", () => {
    renderPanel("page", {
      pagePath: "wiki/docs",
      pageQuery: makePageQuery({
        title: "Intro",
        content: "hello",
        path: "wiki/docs",
        context: {
          repository: "  org/repo-from-context  ",
          page_type: "guide",
        },
      } as WikiPageDetail),
    });
    const spy = screen.getByTestId("ask-spy");
    expect(spy).toHaveAttribute("data-repository", "org/repo-from-context");
    expect(AskPanelSpy.mock.calls[0]?.[0]).toMatchObject({
      repository: "org/repo-from-context",
      pageContext: expect.stringContaining("[Current page: Intro]"),
    });
  });

  it("falls WikiAssistantPanel repository back to trimmed businessId when context repo is whitespace-only", () => {
    renderPanel("page", {
      pagePath: "wiki/docs",
      businessId: "  fallback-biz  ",
      pageQuery: makePageQuery({
        title: "Intro",
        content: "hello",
        path: "wiki/docs",
        context: {
          repository: "   ",
          page_type: "guide",
        },
      } as WikiPageDetail),
    });
    expect(screen.getByTestId("ask-spy")).toHaveAttribute("data-repository", "fallback-biz");
  });

  it("toggle domain review expand and collapse", async () => {
    const user = userEvent.setup();
    renderPanel("page", { pagePath: "" });
    await user.click(screen.getByRole("button", { name: /expand domain review panel/i }));
    expect(screen.getByTestId("wiki-domain-review-mock")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /collapse domain review/i }));
    expect(screen.queryByTestId("wiki-domain-review-mock")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /expand domain review panel/i })).toBeInTheDocument();
  });

  it("ErrorBoundary renders fallback when landing page throws", () => {
    landingCtrl.shouldThrow = true;
    renderPanel("page", { pagePath: "" });
    expect(screen.getByText(/wiki tool panel failed to render/i)).toBeInTheDocument();
    expect(screen.getByText(/WikiLandingPage blew up/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
