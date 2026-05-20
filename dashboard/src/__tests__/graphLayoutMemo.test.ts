import { describe, it, expect } from "vitest";
import { computeDagrePositions, applyNodeStyles } from "../pages/GraphExplorer";

describe("GraphExplorer layout memoization", () => {
  const sampleNodes = [
    { id: "1", name: "FuncA", type: "Function", file: "a.py", line: 1, end_line: 10, is_center: true },
    { id: "2", name: "ClassB", type: "Class", file: "b.py", line: 5, end_line: 20, is_center: false },
  ];
  const sampleEdges = [{ source: "1", target: "2", type: "CALLS" }];

  it("computeDagrePositions returns positions for all nodes", () => {
    const positions = computeDagrePositions(sampleNodes as any, sampleEdges as any);
    expect(positions.size).toBe(2);
    expect(positions.get("1")).toBeDefined();
    expect(positions.get("2")).toBeDefined();
  });

  it("applyNodeStyles uses provided positions without recomputing", () => {
    const positions = new Map([
      ["1", { x: 100, y: 200 }],
      ["2", { x: 300, y: 400 }],
    ]);
    const nodes = applyNodeStyles(sampleNodes as any, positions, false);
    expect(nodes[0].position).toEqual({ x: 100, y: 200 });
    expect(nodes[1].position).toEqual({ x: 300, y: 400 });
  });

  it("highlight change does not require position recomputation", () => {
    const positions = computeDagrePositions(sampleNodes as any, sampleEdges as any);
    const nodesA = applyNodeStyles(sampleNodes as any, positions, false);
    const nodesB = applyNodeStyles(sampleNodes as any, positions, false, new Set(["1"]));
    // Positions are identical
    expect(nodesA[0].position).toEqual(nodesB[0].position);
    // But styles differ (highlight ring)
    expect(nodesA[0].style?.boxShadow).not.toEqual(nodesB[0].style?.boxShadow);
  });
});
