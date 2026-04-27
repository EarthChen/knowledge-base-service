import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, within } from "@testing-library/react";
import { fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiTreeNav from "../WikiTreeNav";
import { renderWithI18n } from "../../../test/renderWithI18n";
import type { WikiTreeNode } from "../../../hooks/wikiTypes";
import { useWikiTree } from "../../../hooks/useWikiTree";

vi.mock("../../../hooks/useWikiTree", () => ({
  useWikiTree: vi.fn(),
}));

const childNode: WikiTreeNode = {
  uid: "c1",
  title: "Leaf",
  label: "Leaf",
  path: "child/path.md",
  page_type: "page",
  depth: 1,
  sort_order: 0,
};

const parentNode: WikiTreeNode = {
  uid: "p1",
  title: "Parent",
  label: "Parent",
  path: "parent",
  page_type: "folder",
  depth: 0,
  sort_order: 0,
  children: [childNode],
};

function renderTree(props?: { activePath?: string }) {
  const client = new QueryClient();
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiTreeNav
          businessId="biz"
          viewType="business_domain"
          activePath={props?.activePath ?? ""}
          onViewChange={vi.fn()}
          wikiTier={null}
          onWikiTierChange={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
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

describe("WikiTreeNav rendering", () => {
  it("renders root tree with folder and expands to show a page link", async () => {
    renderTree();
    const rootTree = screen.getByRole("tree");
    expect(rootTree).toBeInTheDocument();
    expect(within(rootTree).getByText("Parent")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    await waitFor(() => {
      const link = within(rootTree).getByRole("link", { name: "Leaf" });
      expect(link).toHaveAttribute("href", expect.stringContaining("path=child%2Fpath.md"));
    });
  });

  it("marks the active page link when activePath matches a leaf", () => {
    renderTree({ activePath: "child/path.md" });
    const link = screen.getByRole("link", { name: "Leaf" });
    expect(link.className).toContain("bg-sky-50");
  });
});
