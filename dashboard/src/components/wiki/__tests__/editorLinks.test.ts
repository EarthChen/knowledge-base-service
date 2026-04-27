import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  buildIdeHref,
  editorTemplates,
  getWikiLocalRoot,
  parseSourceProtocol,
  wikiLocalRootKey,
} from "../editorLinks";

describe("parseSourceProtocol", () => {
  it("returns null for non-matching hrefs", () => {
    expect(parseSourceProtocol("https://x")).toBeNull();
  });

  it("parses source:// links with repo, path, and line", () => {
    const out = parseSourceProtocol("source://a%2Fb/repo%2Fz/file.ts#L10");
    expect(out).toEqual({
      repository: "a/b",
      filePath: "repo/z/file.ts",
      line: 10,
    });
  });
});

describe("wikiLocalRootKey", () => {
  it("prefixes repository for storage key", () => {
    expect(wikiLocalRootKey("r1")).toBe("wiki-local-root:r1");
  });
});

describe("getWikiLocalRoot", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("returns stored root", () => {
    localStorage.setItem("wiki-local-root:repo", "/tmp/r");
    expect(getWikiLocalRoot("repo")).toBe("/tmp/r");
  });

  it("returns empty string on storage failure", () => {
    const spy = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(getWikiLocalRoot("x")).toBe("");
    spy.mockRestore();
  });
});

describe("buildIdeHref", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("uses relative file path when no local root is set", () => {
    const href = buildIdeHref("cursor", "repo", "src/f.ts", 3);
    expect(href).toBe("cursor://file/src/f.ts:3");
  });

  it("joins local root to file path and strips trailing slash on root", () => {
    localStorage.setItem("wiki-local-root:repo", "/projects/r/");
    expect(buildIdeHref("vscode", "repo", "a.ts", 1)).toBe("vscode://file//projects/r/a.ts:1");
  });

  it("builds idea:// links with encoding", () => {
    expect(buildIdeHref("idea", "r", "p/a.ts", 2)).toMatch(/^idea:\/\/open\?file=/);
    expect(buildIdeHref("idea", "r", "p/a.ts", 2)).toContain("line=2");
  });
});

describe("editorTemplates", () => {
  it("exposes all three link builders", () => {
    expect(editorTemplates.vscode("/x", 1)).toBe("vscode://file//x:1");
    expect(editorTemplates.cursor("/x", 1)).toBe("cursor://file//x:1");
    expect(editorTemplates.idea("/a b", 2)).toContain("line=2");
  });
});
