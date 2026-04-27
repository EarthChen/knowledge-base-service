import { describe, it, expect } from "vitest";
import { escapeRegexChars, parseHighlightTerms } from "./highlightTerms";

describe("escapeRegexChars", () => {
  it("escapes metacharacters so they match literally", () => {
    const q = "a+b*c?^${}()|[]\\";
    const esc = escapeRegexChars(q);
    const re = new RegExp(esc, "g");
    expect("xx a+b*c?^${}()|[]\\ yy".match(re)?.[0]).toBe(q);
  });

  it("does not treat the escaped string as a character class or group", () => {
    const esc = escapeRegexChars("(test)");
    expect(new RegExp(`^${esc}$`).test("(test)")).toBe(true);
    expect(new RegExp(`^${esc}$`).test("test")).toBe(false);
  });
});

describe("parseHighlightTerms", () => {
  it("splits on ASCII whitespace and dedupes case-insensitively", () => {
    // Same length after dedupe: stable order is first-seen, then no reorder among ties.
    expect(parseHighlightTerms("  Foo  bar  FOO  ")).toEqual(["Foo", "bar"]);
  });

  it("treats unspaced CJK as a single term", () => {
    expect(parseHighlightTerms("项目配置说明")).toEqual(["项目配置说明"]);
  });

  it("splits mixed Latin and CJK on spaces", () => {
    expect(parseHighlightTerms("auth 项目")).toEqual(["auth", "项目"]);
  });

  it("splits on ideographic space without breaking unspaced CJK segments", () => {
    // U+3000 between words => separate terms; "项目配置" has no space inside.
    const q = `foo\u3000项目配置\u3000bar`;
    const terms = parseHighlightTerms(q);
    expect(terms[0]).toBe("项目配置");
    expect(new Set(terms)).toEqual(new Set(["项目配置", "foo", "bar"]));
  });

  it("orders longest terms first for regex alternation", () => {
    expect(parseHighlightTerms("a ab abc")).toEqual(["abc", "ab", "a"]);
  });
});
