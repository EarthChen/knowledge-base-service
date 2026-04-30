import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiShell, { WikiToolSuspenseFallback } from "../WikiShell";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { ToastProvider } from "../../Toast";

vi.mock("../../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "default",
    setCurrentBusiness: vi.fn(),
    businesses: [],
    isLoading: false,
    isBound: false,
  }),
}));

vi.mock("../../../hooks/useWikiEvents", () => ({
  useWikiEvents: vi.fn(),
}));

vi.mock("../WikiContent", () => ({ default: () => <div data-testid="mock-wiki-content" /> }));
vi.mock("../AskPanel", () => ({ default: () => <div data-testid="mock-ask" /> }));
vi.mock("../GraphInsightsPanel", () => ({ default: () => <div data-testid="mock-graph-insights" /> }));
vi.mock("../WikiReferencesPanel", () => ({ default: () => <div data-testid="mock-refs" /> }));
vi.mock("../WikiCoverageCard", () => ({ default: () => <div data-testid="mock-coverage" /> }));
vi.mock("../WikiQualityScoreCard", () => ({ default: () => <div data-testid="mock-quality" /> }));
vi.mock("../WikiReferenceGraph", () => ({ default: () => <div data-testid="mock-ref-graph" /> }));
vi.mock("../WikiBusinessExportPanel", () => ({ default: () => <div data-testid="mock-export" /> }));
vi.mock("../WikiLandingPage", () => ({ default: () => <div data-testid="mock-landing" /> }));
vi.mock("../WikiLintPanel", () => ({ default: () => <div data-testid="mock-lint" /> }));
vi.mock("../WikiTreeNav", () => ({ default: () => <div data-testid="mock-tree" /> }));
vi.mock("../WikiTopicTreeNav", () => ({ default: () => <div data-testid="mock-topic-tree" /> }));
vi.mock("../WikiSearchBar", () => ({ default: () => <div data-testid="mock-search" /> }));
vi.mock("../WikiGenerationProgress", () => ({ default: () => <div data-testid="mock-gen-progress" /> }));
vi.mock("../WikiUpdateNotification", () => ({ default: () => <div data-testid="mock-update" /> }));

vi.mock("../../../hooks/useWikiDomainTree", () => ({
  useWikiTopicTree: () => ({ data: { tree: [] }, isLoading: false, isError: false }),
  useWikiDomainTree: () => ({ data: undefined, isLoading: false, isError: false }),
}));

vi.mock("../WikiKnowledgeGraph", () => ({
  default: () => <div data-testid="mock-knowledge-graph" />,
}));

const generateMock = vi.fn().mockResolvedValue({ task_id: null as string | null });
vi.mock("../../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/client")>();
  return {
    ...actual,
    businessWikiGenerate: (...a: unknown[]) => generateMock(...a),
  };
});

function renderShell(initial: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter initialEntries={[initial]}>
          <WikiShell />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("WikiShell", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders shell with landing on page tab and no path", () => {
    renderShell("/wiki?business_id=b1");
    expect(screen.getByTestId("mock-topic-tree")).toBeInTheDocument();
    expect(screen.getByTestId("mock-search")).toBeInTheDocument();
    expect(screen.getByTestId("mock-landing")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Page" })).toBeInTheDocument();
  });

  it("switches to coverage tool tab and shows coverage widgets", async () => {
    const user = userEvent.setup();
    renderShell("/wiki?business_id=b1");
    await user.click(screen.getByRole("tab", { name: "Wiki Coverage" }));
    expect(screen.queryByTestId("mock-landing")).not.toBeInTheDocument();
    expect(screen.getByTestId("mock-coverage")).toBeInTheDocument();
    expect(screen.getByTestId("mock-quality")).toBeInTheDocument();
  });

  it("invoke regenerate uses business generate API and succeeds without task id", async () => {
    const user = userEvent.setup();
    renderShell("/wiki?business_id=b1");
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(generateMock).toHaveBeenCalledWith("b1", "en", true, "full");
  });

  it("wiki tool Suspense fallback uses i18n loading string", () => {
    renderWithI18n(<WikiToolSuspenseFallback />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
