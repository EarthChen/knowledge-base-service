import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import SearchPage from "../SearchPage";
import { renderWithI18n } from "../../test/renderWithI18n";
import { server } from "../../test/mocks/server";

vi.mock("../../components/DeepSearchSection", () => ({
  default: () => <div data-testid="deep-search" />,
}));

vi.mock("../../components/wiki/WikiGlobalSearchBar", () => ({
  default: () => <div data-testid="wiki-search-bar" />,
}));

function renderSearch(initial = "/search") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initial]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SearchPage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 10, git_url: "" }] }),
      ),
      http.post("/api/v1/hybrid", () =>
        HttpResponse.json({
          semantic_matches: [
            {
              uid: "fn-1",
              name: "handleSearch",
              type: "function",
              file: "src/pages/SearchPage.tsx",
              line: 145,
              score: 0.95,
            },
          ],
          graph_context: [
            {
              name: "handler",
              source: "caller",
              relationship: "calls",
              file: "src/a.ts",
              line: 1,
            },
          ],
          total: 1,
          offset: 0,
          limit: 20,
          query: "handleSearch",
        }),
      ),
    );
  });

  it("renders search input and mode tabs", () => {
    renderSearch();
    expect(screen.getByRole("heading", { level: 2, name: /^search$/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search code/i)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /hybrid/i })).toBeInTheDocument();
  });

  it("shows hybrid results from URL query", async () => {
    renderSearch("/search?q=handleSearch&mode=hybrid");
    expect(await screen.findByText("handleSearch")).toBeInTheDocument();
    expect(screen.getByText(/graph context/i)).toBeInTheDocument();
  });

  it("submits a new search query", async () => {
    const user = userEvent.setup();
    renderSearch("/search?mode=hybrid");
    await user.type(screen.getByPlaceholderText(/search code/i), "auth module");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    await waitFor(() => expect(screen.getByDisplayValue("auth module")).toBeInTheDocument());
  });

  it("switches to wiki and deep tabs", async () => {
    const user = userEvent.setup();
    renderSearch("/search?mode=hybrid");
    await user.click(screen.getByRole("tab", { name: /wiki search/i }));
    expect(screen.getByTestId("wiki-search-bar")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /deep research/i }));
    expect(screen.getByTestId("deep-search")).toBeInTheDocument();
  });

  it("exposes tablist ARIA attributes on mode tabs", () => {
    renderSearch("/search?mode=hybrid");
    expect(screen.getByRole("tablist")).toBeInTheDocument();
    const hybridTab = screen.getByRole("tab", { name: /hybrid/i });
    expect(hybridTab).toHaveAttribute("aria-selected", "true");
    expect(hybridTab).toHaveAttribute("id");
    expect(hybridTab).toHaveAttribute("aria-controls");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", hybridTab.id);
  });

  it("ArrowRight moves focus to the next mode tab", async () => {
    renderSearch("/search?mode=hybrid");
    const hybridTab = screen.getByRole("tab", { name: /hybrid/i });
    hybridTab.focus();
    fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /wiki search/i })).toHaveFocus();
    });
  });

  it("shows empty state when hybrid search returns zero results", async () => {
    server.use(
      http.post("/api/v1/hybrid", () =>
        HttpResponse.json({
          semantic_matches: [],
          graph_context: [],
          total: 0,
          offset: 0,
          limit: 20,
          query: "nothing-here",
        }),
      ),
    );
    renderSearch("/search?q=nothing-here&mode=hybrid");
    expect(await screen.findByText(/no results/i)).toBeInTheDocument();
  });
});
