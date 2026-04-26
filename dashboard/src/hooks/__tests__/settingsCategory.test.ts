import { describe, it, expect } from "vitest";
import { getSettingCategory } from "../settingsCategory";

describe("getSettingCategory", () => {
  it("maps system keys", () => {
    expect(getSettingCategory("host")).toBe("system");
    expect(getSettingCategory("require_auth")).toBe("system");
  });

  it("maps storage and embedding prefixes", () => {
    expect(getSettingCategory("falkordb.host")).toBe("storage");
    expect(getSettingCategory("embedding.model_name")).toBe("embedding");
    expect(getSettingCategory("llm.model")).toBe("llm");
  });

  it("classifies wiki feature toggles", () => {
    expect(getSettingCategory("wiki.tree_enabled")).toBe("wiki_features");
    expect(getSettingCategory("wiki.coverage_report_enabled")).toBe("wiki_features");
  });

  it("classifies wiki git fields", () => {
    expect(getSettingCategory("wiki.git_token")).toBe("wiki_git");
    expect(getSettingCategory("wiki.git_publish_mode")).toBe("wiki_git");
  });

  it("classifies wiki generation fields including export_*", () => {
    expect(getSettingCategory("wiki.rag_enabled")).toBe("wiki_generation");
    expect(getSettingCategory("wiki.export_default_view")).toBe("wiki_generation");
    expect(getSettingCategory("wiki.auto_update_on_index")).toBe("wiki_generation");
  });
});
