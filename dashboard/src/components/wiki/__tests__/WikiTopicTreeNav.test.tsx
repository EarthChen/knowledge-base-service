import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiTopicTreeNav from "../WikiTopicTreeNav";

const mockTree = [
  {
    name: "payment",
    page_type: "domain_overview",
    path: "wiki/payment",
    children: [
      {
        name: "payment-core",
        page_type: "topic",
        path: "wiki/payment/payment-core",
        children: [
          {
            name: "deep-leaf",
            page_type: "topic",
            path: "wiki/payment/payment-core/deep",
            children: [],
          },
        ],
      },
      { name: "refund", page_type: "topic", path: "wiki/payment/refund", children: [] },
    ],
  },
  {
    name: "user-management",
    page_type: "domain_overview",
    path: "wiki/user-management",
    children: [],
    review_status: "pending_review",
  },
];

describe("WikiTopicTreeNav", () => {
  it("renders empty state when tree is empty", () => {
    render(<WikiTopicTreeNav tree={[]} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.getByText("暂无主题内容")).toBeInTheDocument();
  });

  it("sets aria-expanded on nodes with children", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    const paymentItem = screen.getByText("payment").closest("[role='treeitem']");
    expect(paymentItem).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByText("payment"));
    expect(paymentItem).toHaveAttribute("aria-expanded", "false");
    const leafItem = screen.getByText("user-management").closest("[role='treeitem']");
    expect(leafItem).not.toHaveAttribute("aria-expanded");
  });

  it("renders domain nodes", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.getByText("payment")).toBeInTheDocument();
    expect(screen.getByText("user-management")).toBeInTheDocument();
  });

  it("root nodes are expanded by default so first-level children are visible", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.getByText("payment-core")).toBeInTheDocument();
    expect(screen.getByText("refund")).toBeInTheDocument();
  });

  it("non-root nodes with children start collapsed", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.queryByText("deep-leaf")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("payment-core"));
    expect(screen.getByText("deep-leaf")).toBeInTheDocument();
  });

  it("calls onSelect when clicking a leaf node", () => {
    const onSelect = vi.fn();
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("payment-core"));
    expect(onSelect).toHaveBeenCalledWith("wiki/payment/payment-core");
  });

  it("shows pending_review badge", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.getByText("待审阅")).toBeInTheDocument();
  });

  it("highlights selected node", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath="wiki/user-management" onSelect={vi.fn()} />);
    const btn = screen.getByText("user-management").closest("button");
    expect(btn?.className).toContain("bg-sky-50");
  });
});
