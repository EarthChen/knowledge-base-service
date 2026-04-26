import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { detectLocale } from "../context";

const STORAGE_KEY = "kb_locale";

describe("detectLocale", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns saved locale from localStorage when valid", () => {
    localStorage.setItem(STORAGE_KEY, "zh");
    vi.stubGlobal("navigator", { language: "en-US" });
    expect(detectLocale()).toBe("zh");
  });

  it("maps browser zh-TW to zh", () => {
    vi.stubGlobal("navigator", { language: "zh-TW" });
    expect(detectLocale()).toBe("zh");
  });

  it("defaults to en for non-Chinese browser languages (e.g. ja)", () => {
    vi.stubGlobal("navigator", { language: "ja-JP" });
    expect(detectLocale()).toBe("en");
  });

  it("defaults to en for de browser language", () => {
    vi.stubGlobal("navigator", { language: "de" });
    expect(detectLocale()).toBe("en");
  });
});
