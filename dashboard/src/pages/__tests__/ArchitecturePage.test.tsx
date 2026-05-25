import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import ArchitecturePage from "../ArchitecturePage";
import { renderWithI18n } from "../../test/renderWithI18n";

vi.mock("../../api/hooks", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/hooks")>();
  return {
    ...mod,
    useP2Stats: () => ({
      data: {
        architecture_layers: { presentation: 4, domain: 8, infrastructure: 2 },
        event_tracking: { kafka_topics: 0, producers: 0, consumers: 0 },
        rpc_contracts: { total_contracts: 0, contract_methods: 0 },
        cross_repo: {
          cross_repo_call_edges: 0,
          di_dependency_edges: 0,
          entity_table_edges: 0,
        },
        quality_overview: null,
      },
      isLoading: false,
    }),
    useRepositories: () => ({
      data: { repositories: [{ repository: "demo", nodes: 10, git_url: "" }] },
    }),
    useArchitectureSearch: () => ({
      data: {
        classes: [
          {
            uid: "cls-1",
            name: "UserService",
            fqn: "demo.UserService",
            repository: "demo",
            methods: [],
          },
        ],
        total_count: 1,
        total: 1,
        layer: "domain",
        repository: null,
        limit: 30,
        offset: 0,
      },
      isLoading: false,
      error: null,
    }),
  };
});

function renderArchitecture() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/architecture?layer=domain"]}>
        <ArchitecturePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ArchitecturePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders architecture title and layer sidebar", () => {
    renderArchitecture();
    expect(screen.getByRole("heading", { name: /architecture/i })).toBeInTheDocument();
    expect(screen.getByText(/layers/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /domain/i })).toBeInTheDocument();
  });

  it("renders search input and entity results", () => {
    renderArchitecture();
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    expect(screen.getByText("UserService")).toBeInTheDocument();
  });
});
