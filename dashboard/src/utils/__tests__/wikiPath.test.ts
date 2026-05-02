import { describe, it, expect } from "vitest";
import { encodeWikiPath } from "../wikiPath";

describe("encodeWikiPath", () => {
  it("encodes path segments", () => {
    expect(encodeWikiPath("foo/bar/baz")).toBe("foo/bar/baz");
  });

  it("encodes special characters", () => {
    expect(encodeWikiPath("src/my file.ts")).toBe("src/my%20file.ts");
  });

  it("strips empty segments from leading/trailing slashes", () => {
    expect(encodeWikiPath("/foo/bar/")).toBe("foo/bar");
  });

  it("handles empty string", () => {
    expect(encodeWikiPath("")).toBe("");
  });
});
