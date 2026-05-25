import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TreeView, type TreeViewNode } from "../TreeView";

const nodes: TreeViewNode[] = [
  {
    id: "a",
    label: "Alpha",
    children: [{ id: "a1", label: "Alpha One" }],
  },
  { id: "b", label: "Beta" },
];

describe("TreeView", () => {
  it("renders nodes", () => {
    render(
      <TreeView
        nodes={nodes}
        selectedId={null}
        onSelect={vi.fn()}
        isExpanded={() => true}
        onToggleExpand={vi.fn()}
      />,
    );
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Alpha One")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("handles expand/collapse toggle", () => {
    const onToggleExpand = vi.fn();
    render(
      <TreeView
        nodes={nodes}
        selectedId={null}
        onSelect={vi.fn()}
        isExpanded={(id) => id !== "a"}
        onToggleExpand={onToggleExpand}
      />,
    );
    expect(screen.queryByText("Alpha One")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Alpha/i }));
    expect(onToggleExpand).toHaveBeenCalledWith("a");
  });

  it("calls onSelect when a node is clicked", () => {
    const onSelect = vi.fn();
    render(
      <TreeView
        nodes={nodes}
        selectedId={null}
        onSelect={onSelect}
        isExpanded={() => true}
        onToggleExpand={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Beta" }));
    expect(onSelect).toHaveBeenCalledWith("b");
  });
});
