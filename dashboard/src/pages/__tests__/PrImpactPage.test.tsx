import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import PrImpactPage from "../PrImpactPage";
import { renderWithI18n } from "../../test/renderWithI18n";

vi.mock("../../api/hooks", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/hooks")>();
  return {
    ...mod,
    useRepositories: () => ({
      data: { repositories: [{ repository: "demo", nodes: 10, git_url: "" }] },
      isLoading: false,
    }),
    useAnalyzeImpact: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    }),
    useFetchPrFiles: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    }),
  };
});

function renderPrImpact() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PrImpactPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("PrImpactPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders PR impact title and repository selector", () => {
    renderPrImpact();
    expect(screen.getByRole("heading", { name: /pr impact/i })).toBeInTheDocument();
    expect(screen.getAllByRole("combobox").length).toBeGreaterThan(0);
  });

  it("renders changed files section and analyze button", () => {
    renderPrImpact();
    expect(screen.getByText("Changed files")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /analyze impact/i })).toBeInTheDocument();
  });

  it("adds a changed file row", async () => {
    const user = userEvent.setup();
    renderPrImpact();
    const pathInputs = screen.getAllByPlaceholderText(/file path/i);
    await user.type(pathInputs[0], "src/app.ts");
    await user.click(screen.getByRole("button", { name: /add file/i }));
    expect(screen.getAllByPlaceholderText(/file path/i).length).toBe(2);
  });
});
