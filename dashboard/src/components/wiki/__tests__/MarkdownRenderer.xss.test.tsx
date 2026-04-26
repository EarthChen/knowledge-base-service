import { render } from "@testing-library/react";
import { describe, expect, it, afterEach, vi } from "vitest";
import MarkdownRenderer from "../MarkdownRenderer";
import { TestI18nProvider } from "../../../i18n/context";
import { getMermaid } from "../mermaidLoader";

vi.mock("../mermaidLoader", () => ({
  getMermaid: vi.fn().mockResolvedValue({ run: vi.fn() }),
}));

describe("MarkdownRenderer XSS / sanitize", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("strips script tags from raw HTML (rehype-sanitize)", () => {
    const { container } = render(
      <TestI18nProvider>
        <MarkdownRenderer
          content={`<p>Hi</p><script>window.__xss = 1</script><p>Bye</p>`}
          businessId="biz"
        />
      </TestI18nProvider>,
    );
    expect(container.querySelectorAll("script")).toHaveLength(0);
  });

  it("does not execute inline handlers on retained elements (sanitized)", () => {
    const { container } = render(
      <TestI18nProvider>
        <MarkdownRenderer
          content={`<p><img src="data:image/gif;base64,R0lGODdhAQABAIAAAAAAAP" alt="x" onerror="window.__xss=1" /></p>`}
          businessId="biz"
        />
      </TestI18nProvider>,
    );
    const img = container.querySelector("img");
    if (img) {
      expect(img.getAttribute("onerror")).toBeFalsy();
    }
  });

  it("keeps mermaid code fences; mermaid is loaded and run via MermaidBlock", async () => {
    const mermaidBlock = '```mermaid\ngraph TD\n  A --> B\n```';
    const { findByText } = render(
      <TestI18nProvider>
        <MarkdownRenderer content={mermaidBlock} businessId="biz" />
      </TestI18nProvider>,
    );
    await findByText("A --> B", { exact: false });
    const el = document.querySelector(".mermaid");
    expect(el).toBeTruthy();
    expect(vi.mocked(getMermaid)).toHaveBeenCalled();
  });
});
