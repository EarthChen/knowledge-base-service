import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import CodeBlock from "../CodeBlock";
import { renderWithI18n } from "../../test/renderWithI18n";

describe("CodeBlock", () => {
  beforeEach(() => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: vi.fn().mockImplementation(() => ({
        matches: false,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })),
    });
  });

  it("renders highlighted code with line numbers", () => {
    renderWithI18n(<CodeBlock code={"def hello():\n    return 1"} filePath="main.py" startLine={1} />);
    expect(screen.getByText("def")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("uses explicit language when provided", () => {
    renderWithI18n(<CodeBlock code="const x = 1;" language="typescript" />);
    expect(screen.getByText("const")).toBeInTheDocument();
  });
});
