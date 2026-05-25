import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ComponentProps } from "react";
import WikiTopicTreeNav from "../WikiTopicTreeNav";
import { TestI18nProvider } from "../../../i18n/context";

const domainTree = [
  {
    uid: "domain-1",
    name: "payment",
    page_type: "domain_overview",
    path: "wiki/payment",
    children: [],
  },
];

function renderTopicTree(props?: Partial<ComponentProps<typeof WikiTopicTreeNav>>) {
  return render(
    <TestI18nProvider>
      <WikiTopicTreeNav
        tree={domainTree}
        selectedPath={null}
        onSelect={vi.fn()}
        onRenameDomain={vi.fn()}
        onDeleteDomain={vi.fn()}
        {...props}
      />
    </TestI18nProvider>,
  );
}

describe("WikiTopicTreeNav a11y", () => {
  it("shows action buttons in the DOM for editable domains without requiring hover", () => {
    renderTopicTree();
    expect(screen.getByRole("button", { name: "Edit display name" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete domain" })).toBeInTheDocument();
  });

  it("action buttons container uses focus-within visibility classes", () => {
    renderTopicTree();
    const actions = screen.getByRole("button", { name: "Edit display name" }).parentElement;
    expect(actions?.className).toContain("group-focus-within:opacity-100");
    expect(actions?.className).toContain("opacity-0");
  });

  it("reveals action buttons when the row receives focus within", () => {
    renderTopicTree();
    const row = screen.getByText("payment").closest(".group") as HTMLElement;
    fireEvent.focusIn(row);
    const editBtn = screen.getByRole("button", { name: "Edit display name" });
    expect(editBtn).not.toHaveClass("hidden");
  });

  it("edit and delete buttons expose aria-label", () => {
    renderTopicTree();
    expect(screen.getByRole("button", { name: "Edit display name" })).toHaveAttribute(
      "aria-label",
      "Edit display name",
    );
    expect(screen.getByRole("button", { name: "Delete domain" })).toHaveAttribute(
      "aria-label",
      "Delete domain",
    );
  });

  it("inline rename input has accessible name", () => {
    renderTopicTree();
    fireEvent.click(screen.getByRole("button", { name: "Edit display name" }));
    expect(screen.getByRole("textbox", { name: "Rename topic" })).toBeInTheDocument();
  });
});
