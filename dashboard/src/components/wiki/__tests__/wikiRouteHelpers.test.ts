import { describe, it, expect } from "vitest";
import { wikiHref, wikiSearchHref, parseWikiSearchParams } from "../wikiRouteHelpers";

describe("wikiHref", () => {
  it("returns /wiki with no args", () => {
    expect(wikiHref()).toBe("/wiki");
  });

  it("returns path param", () => {
    expect(wikiHref("user/auth")).toBe("/wiki?path=user%2Fauth");
  });

  it("includes extra params", () => {
    const href = wikiHref("a/b", { view: "code_structure" });
    expect(href).toContain("path=a%2Fb");
    expect(href).toContain("view=code_structure");
  });
});

describe("wikiSearchHref", () => {
  it("encodes query", () => {
    expect(wikiSearchHref("test query")).toBe("/search?mode=wiki&q=test%20query");
  });
});

describe("parseWikiSearchParams", () => {
  it("parses defaults", () => {
    const result = parseWikiSearchParams(new URLSearchParams());
    expect(result.path).toBeNull();
    expect(result.viewType).toBe("business_domain");
    expect(result.toolTab).toBe("page");
    expect(result.wikiTier).toBeNull();
  });

  it("parses all params", () => {
    const sp = new URLSearchParams("path=a/b&view=code_structure&tool=export&wiki_tier=standard");
    const result = parseWikiSearchParams(sp);
    expect(result.path).toBe("a/b");
    expect(result.viewType).toBe("code_structure");
    expect(result.toolTab).toBe("export");
    expect(result.wikiTier).toBe("standard");
  });
});
