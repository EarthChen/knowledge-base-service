import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiDomainReviewPanel from "../WikiDomainReviewPanel";

const domainTree = [
  {
    name: "payment",
    description: "Payment processing",
    modules: ["PaymentService", "RefundService"],
    children: [],
  },
  {
    name: "user-management",
    description: "User management",
    modules: ["UserService"],
    children: [],
  },
];

describe("WikiDomainReviewPanel", () => {
  it("renders domain cards", () => {
    render(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText("payment")).toBeInTheDocument();
    expect(screen.getByText("user-management")).toBeInTheDocument();
  });

  it("shows module count", () => {
    render(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText("2 modules")).toBeInTheDocument();
    expect(screen.getByText("1 modules")).toBeInTheDocument();
  });

  it("shows pending_review banner", () => {
    render(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.getByText(/域树待审阅/)).toBeInTheDocument();
  });

  it("calls onApprove when clicking approve button", () => {
    const onApprove = vi.fn();
    render(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={onApprove}
        onRegenerate={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /批准/ }));
    expect(onApprove).toHaveBeenCalled();
  });

  it("calls onRegenerate for specific domain", () => {
    const onRegenerate = vi.fn();
    render(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "pending_review" }}
        onApprove={vi.fn()}
        onRegenerate={onRegenerate}
      />,
    );
    const buttons = screen.getAllByText(/重新生成此域/);
    fireEvent.click(buttons[0]);
    expect(onRegenerate).toHaveBeenCalledWith(["payment"]);
  });

  it("hides review controls when approved", () => {
    render(
      <WikiDomainReviewPanel
        domainTree={domainTree}
        reviewStatus={{ domain_tree: "approved" }}
        onApprove={vi.fn()}
        onRegenerate={vi.fn()}
      />,
    );
    expect(screen.queryByText(/域树待审阅/)).not.toBeInTheDocument();
  });
});
