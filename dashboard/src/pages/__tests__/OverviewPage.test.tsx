import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { GraphStats, KnowledgeHealthStats, P2Stats } from "../../api/types";
import { renderWithI18n } from "../../test/renderWithI18n";
import OverviewPage from "../Overview";

const mockStats: GraphStats = {
  function_count: 1,
  class_count: 2,
  module_count: 3,
  document_count: 4,
  calls_count: 5,
  inherits_count: 6,
  imports_count: 7,
  contains_count: 8,
  references_count: 9,
  total_nodes: 10,
  total_edges: 11,
};

const mockHealth: KnowledgeHealthStats = {
  index_coverage: 0.85,
  staleness_hours: 12,
  orphan_ratio: 0.05,
  last_indexed_at: "2026-01-01T00:00:00.000Z",
  total_nodes: 100,
  total_edges: 200,
};

const mockP2: P2Stats = {
  architecture_layers: { presentation: 4, domain: 8 },
  event_tracking: { kafka_topics: 1, producers: 2, consumers: 3 },
  rpc_contracts: { total_contracts: 5, contract_methods: 20 },
  cross_repo: {
    cross_repo_call_edges: 6,
    di_dependency_edges: 7,
    entity_table_edges: 8,
  },
  quality_overview: null,
};

vi.mock("../../api/hooks", () => ({
  useStats: () => ({ data: mockStats, isLoading: false, error: null }),
  useP2Stats: () => ({ data: mockP2, isLoading: false, error: null }),
  useHealthStats: () => ({ data: mockHealth, isLoading: false, error: null }),
}));

/** Chart.js uses canvas; jsdom logs getContext warnings without this stub. */
vi.mock("react-chartjs-2", () => ({
  Bar: () => <div data-testid="mock-chart-bar" />,
  Doughnut: () => <div data-testid="mock-chart-doughnut" />,
}));

describe("OverviewPage", () => {
  it("mounts without crashing", () => {
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });

    const { container } = renderWithI18n(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <OverviewPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(container).toBeTruthy();
  });
});
