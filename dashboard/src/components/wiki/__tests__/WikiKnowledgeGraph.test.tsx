import { describe, it, expect, vi } from "vitest";
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
});
