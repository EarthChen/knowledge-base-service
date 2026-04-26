import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import WikiAnnotationLayer from "../WikiAnnotationLayer";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiAnnotationLayer", () => {
  beforeEach(() => {
    window.getSelection()?.removeAllRanges();
  });

  afterEach(() => {
    window.getSelection()?.removeAllRanges();
  });

  it("renders children", () => {
    renderWithI18n(
      <WikiAnnotationLayer onAddAnnotation={vi.fn()}>
        <div data-testid="child">Hello world</div>
      </WikiAnnotationLayer>,
    );
    expect(screen.getByTestId("child")).toBeInTheDocument();
  });

  it("calls onAddAnnotation when submitting after selection", () => {
    const onAdd = vi.fn();
    const { container } = renderWithI18n(
      <WikiAnnotationLayer onAddAnnotation={onAdd}>
        <p id="p">Select this text</p>
      </WikiAnnotationLayer>,
    );

    const p = container.querySelector("#p")!;
    const range = document.createRange();
    range.selectNodeContents(p);
    const sel = window.getSelection()!;
    sel.removeAllRanges();
    sel.addRange(range);

    const layer = container.firstElementChild!;
    fireEvent.mouseUp(layer);

    expect(screen.getByPlaceholderText(/write a comment/i)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/write a comment/i), {
      target: { value: "note" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
    expect(onAdd).toHaveBeenCalledWith(
      expect.objectContaining({
        comment: "note",
        start: 0,
        end: expect.any(Number),
        selected_text: "Select this text",
      }),
    );
    expect(onAdd.mock.calls[0][0].end).toBeGreaterThan(0);
  });
});
