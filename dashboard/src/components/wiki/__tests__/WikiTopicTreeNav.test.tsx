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

function nodeIconClass(name: string): string {
  const btn = screen.getByText(name).closest("button");
  const svgs = btn?.querySelectorAll("svg") ?? [];
  for (const svg of svgs) {
    const cls = svg.getAttribute("class") ?? "";
    if (!cls.includes("chevron")) return cls;
  }
  return "";
}

describe("WikiTopicTreeNav", () => {
  it("renders empty state when tree is empty", () => {
    render(<WikiTopicTreeNav tree={[]} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.getByText("暂无主题内容")).toBeInTheDocument();
  });

  it("sets aria-expanded on nodes with children", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    const paymentItem = screen.getByText("payment").closest("[role='treeitem']");
    expect(paymentItem).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(screen.getByText("payment"));
    expect(paymentItem).toHaveAttribute("aria-expanded", "true");
    const leafItem = screen.getByText("user-management").closest("[role='treeitem']");
    expect(leafItem).not.toHaveAttribute("aria-expanded");
  });

  it("renders domain nodes", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.getByText("payment")).toBeInTheDocument();
    expect(screen.getByText("user-management")).toBeInTheDocument();
  });

  it("tree starts collapsed when no selectedPath", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(screen.queryByText("payment-core")).not.toBeInTheDocument();
    expect(screen.queryByText("refund")).not.toBeInTheDocument();
  });

  it("auto-expands ancestors when selectedPath is set", () => {
    render(
      <WikiTopicTreeNav tree={mockTree} selectedPath="wiki/payment/payment-core/deep" onSelect={vi.fn()} />,
    );
    expect(screen.getByText("payment-core")).toBeInTheDocument();
    expect(screen.getByText("deep-leaf")).toBeInTheDocument();
  });

  it("non-root nodes with children start collapsed", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath="wiki/payment/refund" onSelect={vi.fn()} />);
    expect(screen.queryByText("deep-leaf")).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("payment-core"));
    expect(screen.getByText("deep-leaf")).toBeInTheDocument();
  });

  it("calls onSelect when clicking a leaf node", () => {
    const onSelect = vi.fn();
    render(<WikiTopicTreeNav tree={mockTree} selectedPath="wiki/payment/refund" onSelect={onSelect} />);
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

  it("uses BookOpen icon for domain_overview nodes", () => {
    render(<WikiTopicTreeNav tree={mockTree} selectedPath={null} onSelect={vi.fn()} />);
    expect(nodeIconClass("payment")).toContain("lucide-book-open");
  });

  it("uses FileText icon for topic nodes", () => {
    render(
      <WikiTopicTreeNav tree={mockTree} selectedPath="wiki/payment/refund" onSelect={vi.fn()} />,
    );
    expect(nodeIconClass("payment-core")).toContain("lucide-file-text");
  });

  it("uses Code2 icon for module_overview nodes", () => {
    const treeWithModule = [
      {
        name: "auth-module",
        page_type: "module_overview",
        path: "wiki/auth/module",
        children: [],
      },
    ];
    render(<WikiTopicTreeNav tree={treeWithModule} selectedPath={null} onSelect={vi.fn()} />);
    expect(nodeIconClass("auth-module")).toContain("lucide-code-xml");
  });
});
