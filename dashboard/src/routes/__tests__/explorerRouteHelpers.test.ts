import { describe, it, expect } from "vitest";
import { explorerGraphHref } from "../explorerRouteHelpers";

describe("explorerGraphHref", () => {
  it("encodes node uid in the explorer path", () => {
    expect(explorerGraphHref("Class:my/repo:ns/C")).toBe(
      "/explorer?node=Class%3Amy%2Frepo%3Ans%2FC",
    );
  });

  it("merges extra search params", () => {
    expect(explorerGraphHref("e1", { q: "hint" })).toBe(
      "/explorer?node=e1&q=hint",
    );
  });
});
