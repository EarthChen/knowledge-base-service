import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiPage from "../WikiPage";
import { renderWithI18n } from "../../test/renderWithI18n";
import { ToastProvider } from "../../components/Toast";

/** Mirrors components/wiki/__tests__/WikiShell.test.tsx mocks — WikiPage only renders WikiShell. */

vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "default",
    setCurrentBusiness: vi.fn(),
    businesses: [],
    isLoading: false,
    isBound: false,
  }),
}));

vi.mock("../../hooks/useWikiEvents", () => ({
  useWikiEvents: vi.fn(() => ({ connectionStatus: "connected" as const })),
}));

vi.mock("../../components/wiki/WikiContent", () => ({
  default: () => <div data-testid="mock-wiki-content" />,
}));
vi.mock("../../components/wiki/AskPanel", () => ({
  default: () => <div data-testid="mock-ask" />,
}));
vi.mock("../../components/wiki/GraphInsightsPanel", () => ({
  default: () => <div data-testid="mock-graph-insights" />,
}));
vi.mock("../../components/wiki/WikiReferencesPanel", () => ({
  default: () => <div data-testid="mock-refs" />,
}));
vi.mock("../../components/wiki/WikiCoverageCard", () => ({
  default: () => <div data-testid="mock-coverage" />,
}));
vi.mock("../../components/wiki/WikiQualityScoreCard", () => ({
  default: () => <div data-testid="mock-quality" />,
}));
vi.mock("../../components/wiki/WikiReferenceGraph", () => ({
  default: () => <div data-testid="mock-ref-graph" />,
}));
vi.mock("../../components/wiki/WikiBusinessExportPanel", () => ({
  default: () => <div data-testid="mock-export" />,
}));
vi.mock("../../components/wiki/WikiLandingPage", () => ({
  default: () => <div data-testid="mock-landing" />,
}));
vi.mock("../../components/wiki/WikiLintPanel", () => ({
  default: () => <div data-testid="mock-lint" />,
}));
vi.mock("../../components/wiki/WikiTreeNav", () => ({
  default: () => <div data-testid="mock-tree" />,
}));
vi.mock("../../components/wiki/WikiTopicTreeNav", () => ({
  default: () => <div data-testid="mock-topic-tree" />,
}));
vi.mock("../../components/wiki/WikiSearchBar", () => ({
  default: () => <div data-testid="mock-search" />,
}));
vi.mock("../../components/wiki/WikiGenerationProgress", () => ({
  default: () => <div data-testid="mock-gen-progress" />,
}));
vi.mock("../../components/wiki/WikiUpdateNotification", () => ({
  default: () => <div data-testid="mock-update" />,
}));

vi.mock("../../hooks/useWikiDomainTree", () => ({
  useWikiTopicTree: () => ({ data: { tree: [] }, isLoading: false, isError: false }),
  useWikiDomainTree: () => ({ data: undefined, isLoading: false, isError: false }),
  useWikiDomainEdges: () => ({ data: undefined, isLoading: false, isError: false }),
}));

vi.mock("../../components/wiki/WikiKnowledgeGraph", () => ({
  default: () => <div data-testid="mock-knowledge-graph" />,
}));

const generateMock = vi.fn().mockResolvedValue({ task_id: null as string | null });
vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    businessWikiGenerate: (...a: unknown[]) => generateMock(...a),
  };
});

function renderWiki(initial: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[initial]}>
          <WikiPage />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("WikiPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("mounts without crashing", () => {
    renderWiki("/wiki?business_id=b1");
    expect(screen.getByTestId("mock-topic-tree")).toBeInTheDocument();
    expect(screen.getByTestId("mock-search")).toBeInTheDocument();
    expect(screen.getByTestId("mock-landing")).toBeInTheDocument();
  });
});
