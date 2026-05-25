import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import WikiTopicTreeNav from "../WikiTopicTreeNav";
import { renderWithI18n } from "../../../test/renderWithI18n";
import type { TopicTreeNode } from "../../../hooks/useWikiDomainTree";

const childOne: TopicTreeNode = {
  name: "Child One",
  page_type: "topic",
  path: "wiki/parent/child-one",
  children: [],
};

const childTwo: TopicTreeNode = {
  name: "Child Two",
  page_type: "topic",
  path: "wiki/parent/child-two",
  children: [],
};

const parentNode: TopicTreeNode = {
  name: "Parent",
  page_type: "domain_overview",
  path: "wiki/parent",
  uid: "parent-uid",
  children: [childOne, childTwo],
};

function renderTopicTree(props?: Partial<ComponentProps<typeof WikiTopicTreeNav>>) {
  return renderWithI18n(
    <WikiTopicTreeNav
      tree={[parentNode]}
      selectedPath={null}
      onSelect={vi.fn()}
      {...props}
    />,
  );
}

function treeItems() {
  return screen.getAllByRole("treeitem");
}

function focusedTreeItem() {
  return treeItems().find((item) => item.getAttribute("tabindex") === "0");
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("WikiTopicTreeNav keyboard navigation", () => {
  it("ArrowDown moves focus to the next visible treeitem", async () => {
    renderTopicTree();
    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowDown" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Child One");
    });
  });

  it("ArrowUp moves focus to the previous visible treeitem", async () => {
    renderTopicTree();
    const items = treeItems();
    fireEvent.focus(items[2]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowUp" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Child One");
    });
  });

  it("ArrowRight expands a collapsed node", async () => {
    renderTopicTree();
    fireEvent.click(screen.getByText("Parent"));
    await waitFor(() => expect(screen.queryByText("Child One")).not.toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "ArrowRight" });

    await waitFor(() => {
      expect(items[0]).toHaveAttribute("aria-expanded", "true");
      expect(screen.getByText("Child One")).toBeInTheDocument();
    });
  });

  it("ArrowLeft collapses an expanded node", async () => {
    renderTopicTree();
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
    renderTopicTree();
    await waitFor(() => expect(screen.getByText("Child Two")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[2]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "Home" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Parent");
    });
  });

  it("End focuses the last visible treeitem", async () => {
    renderTopicTree();
    await waitFor(() => expect(screen.getByText("Child Two")).toBeInTheDocument());

    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "End" });

    await waitFor(() => {
      expect(focusedTreeItem()?.textContent).toContain("Child Two");
    });
  });

  it("Enter selects the focused item", () => {
    const onSelect = vi.fn();
    renderTopicTree({ onSelect });
    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: "Enter" });
    expect(onSelect).toHaveBeenCalledWith("wiki/parent");
  });

  it("Space selects the focused item", () => {
    const onSelect = vi.fn();
    renderTopicTree({ onSelect });
    const items = treeItems();
    fireEvent.focus(items[0]);
    fireEvent.keyDown(screen.getByRole("tree"), { key: " " });
    expect(onSelect).toHaveBeenCalledWith("wiki/parent");
  });
});
