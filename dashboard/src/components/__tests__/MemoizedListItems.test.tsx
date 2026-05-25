import { describe, it, expect } from "vitest";
import SearchResultCard from "../SearchResultCard";
import { MemoizedSourceRef } from "../wiki/AskPanel";

describe("memoized list item components", () => {
  it("SearchResultCard is wrapped with React.memo", () => {
    const type = (SearchResultCard as unknown as { $$typeof: symbol }).$$typeof;
    expect(type).toBe(Symbol.for("react.memo"));
  });

  it("SourceRef is wrapped with React.memo", () => {
    const type = (MemoizedSourceRef as unknown as { $$typeof: symbol }).$$typeof;
    expect(type).toBe(Symbol.for("react.memo"));
  });
});
