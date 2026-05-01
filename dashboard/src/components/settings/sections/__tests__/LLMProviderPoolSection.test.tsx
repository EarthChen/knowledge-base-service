import { describe, expect, it } from "vitest";

describe("LLMProviderPoolSection", () => {
  it("can be imported", async () => {
    const mod = await import("../LLMProviderPoolSection");
    expect(mod.default).toBeDefined();
  });
});
