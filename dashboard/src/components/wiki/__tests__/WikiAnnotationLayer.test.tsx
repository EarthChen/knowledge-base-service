import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WikiAnnotationLayer from "../WikiAnnotationLayer";
import { renderWithI18n } from "../../../test/renderWithI18n";
import type { WikiAnnotation } from "../../../hooks/wikiTypes";

const annotation: WikiAnnotation = {
  annotation_id: "a1",
  page_uid: "page-1",
  text_range_start: 0,
  text_range_end: 5,
  selected_text: "Hello",
  comment: "Note",
  author: "tester",
  created_at: "2026-01-01T00:00:00.000Z",
};

describe("WikiAnnotationLayer", () => {
  it("renders children and applies annotation highlights", () => {
    renderWithI18n(
      <WikiAnnotationLayer
        onAddAnnotation={vi.fn()}
        annotations={[annotation]}
        highlightSourceKey="doc-1"
      >
        <p>Hello world</p>
      </WikiAnnotationLayer>,
    );
    expect(document.querySelector("mark[data-wiki-ann]")).toHaveTextContent("Hello");
    expect(screen.getByText(/world/)).toBeInTheDocument();
  });

  it("opens comment input after text selection", async () => {
    const onAdd = vi.fn();
    renderWithI18n(
      <WikiAnnotationLayer onAddAnnotation={onAdd} annotations={[]}>
        <p id="wiki-body">Hello world</p>
      </WikiAnnotationLayer>,
    );
    const paragraph = screen.getByText("Hello world");
    const range = document.createRange();
    range.selectNodeContents(paragraph.firstChild!);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
    fireEvent.mouseUp(paragraph);
    const textarea = await screen.findByPlaceholderText(/write a comment/i);
    await userEvent.type(textarea, "Looks good");
    await userEvent.click(screen.getByRole("button", { name: /^add$/i }));
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({ selected_text: "Hello world", comment: "Looks good" }),
    );
  });
});
