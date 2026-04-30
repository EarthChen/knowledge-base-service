import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiPageReviewBar from "../WikiPageReviewBar";

describe("WikiPageReviewBar", () => {
  it("renders action buttons", () => {
    render(
      <WikiPageReviewBar
        pagePath="wiki/p"
        currentStatus="pending_review"
        onStatusChange={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText("✓")).toBeInTheDocument();
    expect(screen.getByText("✗")).toBeInTheDocument();
    expect(screen.getByText("📝")).toBeInTheDocument();
    expect(screen.getByText("重新生成")).toBeInTheDocument();
  });

  it("calls onStatusChange with approved on check click", () => {
    const onChange = vi.fn();
    render(
      <WikiPageReviewBar
        pagePath="wiki/p"
        currentStatus="pending_review"
        onStatusChange={onChange}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("✓"));
    expect(onChange).toHaveBeenCalledWith("wiki/p", "approved", "");
  });

  it("calls onStatusChange with needs_revision on X click", () => {
    const onChange = vi.fn();
    render(
      <WikiPageReviewBar
        pagePath="wiki/p"
        currentStatus="pending_review"
        onStatusChange={onChange}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByText("✗"));
    expect(onChange).toHaveBeenCalledWith("wiki/p", "needs_revision", "");
  });

  it("calls onRegenerate on regenerate click", () => {
    const onRegen = vi.fn();
    render(
      <WikiPageReviewBar
        pagePath="wiki/p"
        currentStatus="pending_review"
        onStatusChange={vi.fn()}
        onRegenerate={onRegen}
      />,
    );
    fireEvent.click(screen.getByText("重新生成"));
    expect(onRegen).toHaveBeenCalledWith("wiki/p");
  });
});
