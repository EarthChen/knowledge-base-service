import { describe, it, expect } from "vitest";
import { parseWikilinks, replaceWikilinksWithHtml } from "../wikilinkParser";

describe("parseWikilinks", () => {
  it("parses simple wikilink", () => {
    const result = parseWikilinks("See [[user/auth]]");
    expect(result).toEqual([{ raw: "[[user/auth]]", path: "user/auth", label: "auth" }]);
  });

  it("parses wikilink with label", () => {
    const result = parseWikilinks("[[user/auth|Authentication]]");
    expect(result).toEqual([
      { raw: "[[user/auth|Authentication]]", path: "user/auth", label: "Authentication" },
    ]);
  });

  it("parses multiple wikilinks", () => {
    const result = parseWikilinks("[[a/b]] and [[c/d|D]]");
    expect(result).toHaveLength(2);
  });

  it("returns empty for no wikilinks", () => {
    expect(parseWikilinks("plain text")).toEqual([]);
  });
});

describe("replaceWikilinksWithHtml", () => {
  it("replaces wikilink with HTML element", () => {
    const result = replaceWikilinksWithHtml("See [[user/auth]]");
    expect(result).toContain("<wikilink");
    expect(result).toContain('data-path="user%2Fauth"');
    expect(result).toContain("auth</wikilink>");
  });

  it("uses custom label", () => {
    const result = replaceWikilinksWithHtml("[[path|Label]]");
    expect(result).toContain("Label</wikilink>");
  });
});
