import { describe, expect, it } from "vitest";
import { getErrorMessage } from "../errorUtils";

describe("getErrorMessage", () => {
  it("returns message for Error instances", () => {
    expect(getErrorMessage(new Error("oops"))).toBe("oops");
  });

  it("returns string values as-is", () => {
    expect(getErrorMessage("plain")).toBe("plain");
  });

  it("uses fallback for unknown values when provided", () => {
    expect(getErrorMessage(42, "fallback")).toBe("fallback");
  });

  it("returns empty string for unknown values without fallback", () => {
    expect(getErrorMessage(null)).toBe("");
  });
});
