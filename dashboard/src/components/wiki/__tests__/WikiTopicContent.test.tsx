import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiTopicContent from "../WikiTopicContent";

// Mock MarkdownRenderer to just render content as text
vi.mock("../MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <div data-testid="md">{content}</div>,
}));

describe("WikiTopicContent", () => {
  const page = {
    title: "Payment Service",
    content: "## 业务概述\nPayment handling.",
    path: "wiki/payment",
    page_type: "topic",
    domain: "payment",
    review_status: "pending_review",
  };

  it("renders page title", () => {
    render(<WikiTopicContent page={page} onReviewAction={vi.fn()} />);
    expect(screen.getByText("Payment Service")).toBeInTheDocument();
  });

  it("renders markdown content", () => {
    render(<WikiTopicContent page={page} onReviewAction={vi.fn()} />);
    expect(screen.getByTestId("md")).toHaveTextContent("Payment handling");
  });

  it("shows review status badge", () => {
    render(<WikiTopicContent page={page} onReviewAction={vi.fn()} />);
    expect(screen.getByText("待审阅")).toBeInTheDocument();
  });

  it("calls onReviewAction with approve", () => {
    const onAction = vi.fn();
    render(<WikiTopicContent page={page} onReviewAction={onAction} />);
    fireEvent.click(screen.getByText("通过"));
    expect(onAction).toHaveBeenCalledWith("approve");
  });

  it("calls onReviewAction with regenerate", () => {
    const onAction = vi.fn();
    render(<WikiTopicContent page={page} onReviewAction={onAction} />);
    fireEvent.click(screen.getByText("重新生成"));
    expect(onAction).toHaveBeenCalledWith("regenerate");
  });
});
