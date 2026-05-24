import { type ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { api } from "../../../api/client";
import * as useBusinessFlowsModule from "../../../hooks/useBusinessFlows";
import WikiBusinessFlowGraph from "../WikiBusinessFlowGraph";

vi.mock("../../../api/client", () => ({ api: vi.fn() }));

vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  return {
    ...actual,
    ReactFlow: ({
      nodes,
      edges,
    }: {
      nodes: Array<{ id: string; data: { label: string } }>;
      edges: unknown[];
    }) => (
      <div data-testid="react-flow">
        <span data-testid="node-count">{nodes.length} nodes</span>
        <span data-testid="edge-count">{edges.length} edges</span>
      </div>
    ),
    Background: () => null,
    Controls: () => null,
    Handle: () => null,
    ReactFlowProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  };
});

describe("WikiBusinessFlowGraph with dagre", () => {
  it("renders flow graph container", () => {
    vi.spyOn(useBusinessFlowsModule, "useBusinessFlows").mockReturnValue({
      data: {
        nodes: [
          { uid: "bf:1", title: "Create Order", type: "business_flow" },
          { uid: "fs:1", title: "Validate Input", type: "flow_step" },
        ],
        edges: [{ source: "bf:1", target: "fs:1", label: "step 1" }],
      },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useBusinessFlowsModule.useBusinessFlows>);
    renderWithI18n(<WikiBusinessFlowGraph businessId="test" />);
    expect(screen.getByTestId("flow-graph-container")).toBeTruthy();
    expect(screen.getByTestId("node-count")).toHaveTextContent("2 nodes");
    expect(screen.getByTestId("edge-count")).toHaveTextContent("1 edges");
  });
});

describe("WikiBusinessFlowGraph", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("renders flow container", async () => {
    vi.mocked(api).mockResolvedValue({ nodes: [], edges: [] });
    const WikiBusinessFlowGraphModule = (await import("../WikiBusinessFlowGraph")).default;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <WikiBusinessFlowGraphModule businessId="default" />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("flow-graph-container")).toBeTruthy();
  });

  it("shows error when flows request fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("upstream failed"));
    const WikiBusinessFlowGraphModule = (await import("../WikiBusinessFlowGraph")).default;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderWithI18n(
      <QueryClientProvider client={qc}>
        <WikiBusinessFlowGraphModule businessId="default" />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText("Failed to load flows: upstream failed"),
    ).toBeInTheDocument();
  });
});
