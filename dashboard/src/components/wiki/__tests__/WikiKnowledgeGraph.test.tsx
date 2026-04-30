import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import WikiKnowledgeGraph from "../WikiKnowledgeGraph";

vi.mock("@xyflow/react", () => ({
  ReactFlow: ({ nodes, edges }: { nodes: unknown[]; edges: unknown[] }) => (
    <div data-testid="react-flow">
      <span data-testid="node-count">{nodes.length} nodes</span>
      <span data-testid="edge-count">{edges.length} edges</span>
    </div>
  ),
  Background: () => null,
  Controls: () => null,
  MiniMap: () => null,
}));

describe("WikiKnowledgeGraph", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const domains = [
    { id: "payment", label: "Payment", children: [] },
    { id: "user", label: "User", children: [] },
    { id: "messaging", label: "Messaging", children: [] },
  ];
  const edges = [
    { source: "payment", target: "user", label: "CALLS" },
    { source: "messaging", target: "user", label: "CALLS" },
  ];

  it("renders xyflow with nodes and edges", () => {
    render(<WikiKnowledgeGraph domains={domains} domainEdges={edges} onNodeClick={vi.fn()} />);
    expect(screen.getByTestId("react-flow")).toBeInTheDocument();
    expect(screen.getByTestId("node-count")).toHaveTextContent("3 nodes");
    expect(screen.getByTestId("edge-count")).toHaveTextContent("2 edges");
  });

  it("shows empty state when no domains", () => {
    render(<WikiKnowledgeGraph domains={[]} domainEdges={[]} onNodeClick={vi.fn()} />);
    expect(screen.getByText(/暂无域关系数据/)).toBeInTheDocument();
  });

  it("shows loading state when isLoading", () => {
    render(
      <WikiKnowledgeGraph
        domains={domains}
        domainEdges={edges}
        onNodeClick={vi.fn()}
        isLoading
      />,
    );
    expect(screen.getByText("加载中...")).toBeInTheDocument();
    expect(screen.queryByTestId("react-flow")).not.toBeInTheDocument();
  });

  it("shows error state when error is set", () => {
    render(
      <WikiKnowledgeGraph
        domains={domains}
        domainEdges={edges}
        onNodeClick={vi.fn()}
        error={new Error("network down")}
      />,
    );
    expect(screen.getByText(/加载失败:/)).toBeInTheDocument();
    expect(screen.getByText(/network down/)).toBeInTheDocument();
    expect(screen.queryByTestId("react-flow")).not.toBeInTheDocument();
  });

  it("observes documentElement class changes for dark mode via MutationObserver", () => {
    const observe = vi.fn();
    const disconnect = vi.fn();

    class MockMutationObserver {
      observe = observe;
      disconnect = disconnect;
      constructor(_cb: MutationCallback) {}
    }

    vi.stubGlobal("MutationObserver", MockMutationObserver);

    render(<WikiKnowledgeGraph domains={domains} domainEdges={edges} onNodeClick={vi.fn()} />);

    expect(observe).toHaveBeenCalledWith(
      document.documentElement,
      expect.objectContaining({
        attributes: true,
        attributeFilter: ["class"],
      }),
    );
  });
});
