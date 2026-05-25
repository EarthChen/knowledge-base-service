import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import MarkdownRenderer from "../MarkdownRenderer";
import { renderWithI18n } from "../../../test/renderWithI18n";

vi.mock("../mermaidLoader", () => ({
  getMermaid: vi.fn(() => Promise.resolve({ render: vi.fn() })),
}));

describe("MarkdownRenderer", () => {
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

  it("renders markdown headings and paragraphs", () => {
    renderWithI18n(<MarkdownRenderer content={"# Hello World\n\nSome **bold** text."} />);
    expect(screen.getByRole("heading", { name: "Hello World" })).toBeInTheDocument();
    expect(screen.getByText("bold")).toBeInTheDocument();
  });
});
