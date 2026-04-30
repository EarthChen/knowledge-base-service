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

  it("shows inline notes for 📝 and submits needs_revision with notes", () => {
    const onChange = vi.fn();
    render(
      <WikiPageReviewBar
        pagePath="wiki/p"
        currentStatus="pending_review"
        onStatusChange={onChange}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTitle("添加意见"));
    const input = screen.getByPlaceholderText("审阅意见...");
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "Add diagrams" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onChange).toHaveBeenCalledWith("wiki/p", "needs_revision", "Add diagrams");
    expect(screen.getByTitle("添加意见")).toBeInTheDocument();
  });

  it("submits inline notes via 确定 and closes on ✕", () => {
    const onChange = vi.fn();
    render(
      <WikiPageReviewBar
        pagePath="wiki/x"
        currentStatus="approved"
        onStatusChange={onChange}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTitle("添加意见"));
    fireEvent.change(screen.getByPlaceholderText("审阅意见..."), {
      target: { value: "Minor typos" },
    });
    fireEvent.click(screen.getByText("确定"));
    expect(onChange).toHaveBeenCalledWith("wiki/x", "needs_revision", "Minor typos");

    fireEvent.click(screen.getByTitle("添加意见"));
    fireEvent.change(screen.getByPlaceholderText("审阅意见..."), { target: { value: "n" } });
    fireEvent.click(screen.getByText("✕"));
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});
