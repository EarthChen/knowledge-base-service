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

  it("shows fallback when page is null or undefined", () => {
    // Props widened to allow null — verifies no crash and placeholder copy
    const { rerender } = render(
      <WikiTopicContent page={null} onReviewAction={vi.fn()} />,
    );
    expect(screen.getByText("请选择一个主题页面")).toBeInTheDocument();

    rerender(<WikiTopicContent page={undefined} onReviewAction={vi.fn()} />);
    expect(screen.getByText("请选择一个主题页面")).toBeInTheDocument();
  });

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

  it("shows inline notes input for 标记修改 and submits on Enter", () => {
    const onAction = vi.fn();
    render(<WikiTopicContent page={page} onReviewAction={onAction} />);
    fireEvent.click(screen.getByText("标记修改"));
    const input = screen.getByPlaceholderText("输入修改意见...");
    expect(input).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "Fix the intro" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onAction).toHaveBeenCalledWith("needs_revision", "Fix the intro");
    expect(screen.getByText("标记修改")).toBeInTheDocument();
  });

  it("submits inline notes via 提交 button and cancels with 取消", () => {
    const onAction = vi.fn();
    render(<WikiTopicContent page={page} onReviewAction={onAction} />);
    fireEvent.click(screen.getByText("标记修改"));
    const input = screen.getByPlaceholderText("输入修改意见...");
    fireEvent.change(input, { target: { value: "Need examples" } });
    fireEvent.click(screen.getByText("提交"));
    expect(onAction).toHaveBeenCalledWith("needs_revision", "Need examples");

    fireEvent.click(screen.getByText("标记修改"));
    fireEvent.change(screen.getByPlaceholderText("输入修改意见..."), { target: { value: "x" } });
    fireEvent.click(screen.getByText("取消"));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(screen.getByText("标记修改")).toBeInTheDocument();
  });
});
