import { render } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import MarkdownRenderer from "../MarkdownRenderer";
import { TestI18nProvider } from "../../../i18n/context";
import * as headingUtils from "../headingUtils";

describe("wiki MarkdownRenderer", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not call parseMarkdownHeadings when headings are provided", () => {
    const spy = vi.spyOn(headingUtils, "parseMarkdownHeadings");
    const headings = [{ level: 1, text: "Hello", id: "hello" }];
    render(
      <TestI18nProvider>
        <MarkdownRenderer
          content="# Hello\n"
          businessId="biz"
          headings={headings}
        />
      </TestI18nProvider>,
    );
    expect(spy).not.toHaveBeenCalled();
  });

  it("calls parseMarkdownHeadings when headings are omitted", () => {
    const spy = vi.spyOn(headingUtils, "parseMarkdownHeadings");
    render(
      <TestI18nProvider>
        <MarkdownRenderer content="# Only\n" businessId="biz" />
      </TestI18nProvider>,
    );
    expect(spy).toHaveBeenCalled();
  });
});
