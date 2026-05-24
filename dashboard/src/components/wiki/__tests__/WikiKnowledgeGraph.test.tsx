import type { ComponentProps } from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import type { Node, Edge } from "@xyflow/react";
import WikiKnowledgeGraph, { primaryLayer, layoutWithDagre } from "../WikiKnowledgeGraph";
import { renderWithI18n } from "../../../test/renderWithI18n";

vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  return {
    ...actual,
    ReactFlow: ({
      nodes,
      edges,
      onNodeClick,
    }: {
      nodes: Array<{ id: string; data: { label: string } }>;
      edges: unknown[];
      onNodeClick?: (event: unknown, node: { id: string }) => void;
    }) => (
      <div data-testid="react-flow">
        <span data-testid="node-count">{nodes.length} nodes</span>
        <span data-testid="edge-count">{edges.length} edges</span>
        {nodes.map((n) => (
          <button
            key={n.id}
            type="button"
            data-testid={`node-${n.id}`}
            onClick={(e) => onNodeClick?.(e, n)}
          >
            {n.data.label}
          </button>
        ))}
      </div>
    ),
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
  };
});

const renderGraph = (props: ComponentProps<typeof WikiKnowledgeGraph>) =>
  renderWithI18n(
    <WikiKnowledgeGraph {...props} />,
  );

describe("primaryLayer", () => {
  it("returns unknown when empty", () => {
    expect(primaryLayer({})).toBe("unknown");
  });

  it("picks highest count", () => {
    expect(primaryLayer({ api: 3, service: 5 })).toBe("service");
  });
});

describe("layoutWithDagre", () => {
  it("returns positioned nodes", () => {
    const nodes: Node[] = [
      { id: "a", position: { x: 0, y: 0 }, data: { label: "A" } },
      { id: "b", position: { x: 0, y: 0 }, data: { label: "B" } },
      { id: "c", position: { x: 0, y: 0 }, data: { label: "C" } },
    ];
    const edges: Edge[] = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "b", target: "c" },
    ];
    const laidOut = layoutWithDagre(nodes, edges);
    for (const n of laidOut) {
      expect(n.position.x).toBeDefined();
      expect(n.position.y).toBeDefined();
      expect(typeof n.position.x).toBe("number");
      expect(typeof n.position.y).toBe("number");
    }
  });
});

describe("WikiKnowledgeGraph", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const flatDomains = [
    { id: "payment", label: "Payment", children: [] as string[], architectureLayers: { api: 2 } },
    { id: "user", label: "User", children: [] as string[], architectureLayers: { service: 3 } },
    { id: "messaging", label: "Messaging", children: [] as string[], architectureLayers: { data: 1 } },
  ];
  const flatEdges = [
    { source: "payment", target: "user", label: "CALLS" },
    { source: "messaging", target: "user", label: "CALLS" },
  ];

  it("renders loading state", () => {
    renderGraph({
      domains: flatDomains,
      domainEdges: flatEdges,
      onNodeClick: vi.fn(),
      isLoading: true,
    });
    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByTestId("react-flow")).not.toBeInTheDocument();
  });

  it("renders error state", () => {
    renderGraph({
      domains: flatDomains,
      domainEdges: flatEdges,
      onNodeClick: vi.fn(),
      error: new Error("fail"),
    });
    expect(screen.getByText(/Failed to load:/)).toBeInTheDocument();
    expect(screen.getByText(/fail/)).toBeInTheDocument();
    expect(screen.queryByTestId("react-flow")).not.toBeInTheDocument();
  });

  it("renders empty state", () => {
    renderGraph({ domains: [], domainEdges: [], onNodeClick: vi.fn() });
    expect(screen.getByText("No domain relationship data")).toBeInTheDocument();
  });

  it("renders domain nodes", () => {
    renderGraph({
      domains: [
        { id: "a", label: "Alpha", children: [], architectureLayers: { api: 1 } },
        { id: "b", label: "Beta", children: [], architectureLayers: { service: 2 } },
      ],
      domainEdges: [],
      onNodeClick: vi.fn(),
    });
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("renders xyflow with nodes and edges", () => {
    renderGraph({ domains: flatDomains, domainEdges: flatEdges, onNodeClick: vi.fn() });
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
    expect(screen.getByTestId("node-count")).toHaveTextContent("3 nodes");
    expect(screen.getByTestId("edge-count")).toHaveTextContent("2 edges");
  });

  it("expand collapse toggle", () => {
    const onNodeClick = vi.fn();
    const domains = [
      {
        id: "parent",
        label: "Parent",
        children: ["child"],
        architectureLayers: { service: 1 },
      },
      {
        id: "child",
        label: "Child",
        children: [],
        architectureLayers: { api: 2 },
      },
    ];
    renderGraph({ domains, domainEdges: [], onNodeClick });

    expect(screen.queryByText("Child")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("node-parent"));
    expect(screen.getByText("Child")).toBeInTheDocument();
    expect(onNodeClick).toHaveBeenCalledWith("parent");

    fireEvent.click(screen.getByTestId("node-parent"));
    expect(screen.queryByText("Child")).not.toBeInTheDocument();
  });

  it("observes documentElement class changes for dark mode via MutationObserver", () => {
    const observe = vi.fn();
    const disconnect = vi.fn();

    class MockMutationObserver {
      observe = observe;
      disconnect = disconnect;
      constructor() {}
    }

    vi.stubGlobal("MutationObserver", MockMutationObserver);

    renderGraph({ domains: flatDomains, domainEdges: flatEdges, onNodeClick: vi.fn() });

    expect(observe).toHaveBeenCalledWith(
      document.documentElement,
      expect.objectContaining({
        attributes: true,
        attributeFilter: ["class"],
      }),
    );
  });
});
