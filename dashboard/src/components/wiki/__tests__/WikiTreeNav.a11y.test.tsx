import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, fireEvent } from "@testing-library/react";
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
  path: "child/path",
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

beforeEach(() => {
  vi.mocked(useWikiTree).mockReturnValue({
    data: { tree: [parentNode] },
    isLoading: false,
    isError: false,
    isPending: false,
    isSuccess: true,
  } as ReturnType<typeof useWikiTree>);
});

describe("WikiTreeNav a11y", () => {
  it("sets aria-label for expand and collapse on folder toggles", async () => {
    renderTree();
    const expand = screen.getByRole("button", { name: "Expand" });
    expect(expand).toBeInTheDocument();
    fireEvent.click(expand);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Collapse" })).toBeInTheDocument();
    });
  });
});
