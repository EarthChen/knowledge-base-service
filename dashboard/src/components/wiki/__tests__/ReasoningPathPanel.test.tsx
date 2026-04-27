import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ReasoningPathPanel } from "../ReasoningPathPanel";

describe("ReasoningPathPanel", () => {
  const samplePath = {
    stages: [
      { stage_name: "search", retriever: "vector", entity_hits: ["Foo", "Bar"], score: 0.9, metadata: {} },
      { stage_name: "graph_expand", retriever: "graph", entity_hits: ["Baz"], score: null, metadata: {} },
    ],
    answer_entities: ["Foo", "Baz"],
  };

  it("renders nothing when no path", () => {
    const { container } = render(<ReasoningPathPanel reasoningPath={null} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders collapsed by default", () => {
    render(<ReasoningPathPanel reasoningPath={samplePath} />);
    expect(screen.getByText(/Reasoning Path/)).toBeInTheDocument();
    expect(screen.queryByText("search")).not.toBeInTheDocument();
  });

  it("expands on click", () => {
    render(<ReasoningPathPanel reasoningPath={samplePath} />);
    fireEvent.click(screen.getByText(/Reasoning Path/));
    expect(screen.getByText("search")).toBeInTheDocument();
    expect(screen.getByText("vector")).toBeInTheDocument();
    expect(screen.getAllByText("Foo").length).toBeGreaterThanOrEqual(1);
  });
});
