import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiTreeNav from "../WikiTreeNav";
import { renderWithI18n } from "../../../test/renderWithI18n";
import type { WikiTreeNode } from "../../../hooks/wikiTypes";
import { useWikiTree } from "../../../hooks/useWikiTree";

vi.mock("../../../hooks/useWikiTree", () => ({
  useWikiTree: vi.fn(),
}));

const childOne: WikiTreeNode = {
  uid: "c1",
  title: "Child One",
  label: "Child One",
  path: "parent/child-one",
  page_type: "page",
  depth: 1,
  sort_order: 0,
};

const childTwo: WikiTreeNode = {
  uid: "c2",
  title: "Child Two",
  label: "Child Two",
  path: "parent/child-two",
  page_type: "page",
  depth: 1,
  sort_order: 1,
};

const parentNode: WikiTreeNode = {
  uid: "p1",
  title: "Parent",
  label: "Parent",
  path: "parent",
  page_type: "folder",
  depth: 0,
  sort_order: 0,
  children: [childOne, childTwo],
};

function renderTree() {
  const client = new QueryClient();
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiTreeNav
          businessId="biz"
          viewType="business_domain"
          activePath=""
          onViewChange={vi.fn()}
          wikiTier={null}
          onWikiTierChange={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function treeItems() {
  return screen.getAllByRole("treeitem");
}

function focusedTreeItem() {
  return treeItems().find((item) => item.getAttribute("tabindex") === "0");
}

beforeEach(() => {
  vi.mocked(useWikiTree).mockReturnValue({
    data: { tree: [parentNode] },
    isLoading: false,
    isError: false,
    isPending: false,
    isSuccess: true,
  } as ReturnType<typeof useWikiTree>);
});

describe("WikiTreeNav keyboard navigation", () => {
  it("ArrowDown moves focus to the next visible treeitem", async () => {
    renderTree();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    await waitFor(() => expect(screen.getByText("Child One")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowDown" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Child One");
    });
  });

  it("ArrowUp moves focus to the previous visible treeitem", async () => {
    renderTree();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    await waitFor(() => expect(screen.getByText("Child Two")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[2]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowUp" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Child One");
    });
  });

  it("ArrowRight expands a collapsed node", async () => {
    renderTree();
    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowRight" });

    await waitFor(() => {
      expect(items[0]).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByText("Child One")).toBeInTheDocument();
    });
  });

  it("ArrowLeft collapses an expanded node", async () => {
    renderTree();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    await waitFor(() => expect(screen.getByText("Child One")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowLeft" });

    await waitFor(() => {
      expect(items[0]).toHaveAttribute("aria-expanded", "false");
      expect(screen.queryByText("Child One")).not.toBeInTheDocument();
    });
  });

  it("Home focuses the first visible treeitem", async () => {
    renderTree();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    await waitFor(() => expect(screen.getByText("Child Two")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[2]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "Home" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Parent");
    });
  });

  it("End focuses the last visible treeitem", async () => {
    renderTree();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    await waitFor(() => expect(screen.getByText("Child Two")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "End" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Child Two");
    });
  });
});
