import { describe, it, expect } from "vitest";
import { getMermaid } from "../mermaidLoader";

describe("getMermaid", () => {
  it("returns the same promise for repeated calls (shared lazy init)", () => {
    const a = getMermaid();
    const b = getMermaid();
    expect(a).toBe(b);
  });
});
