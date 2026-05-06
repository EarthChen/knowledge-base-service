import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiSearchBar from "../WikiSearchBar";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { wikiSearchOptionId } from "../WikiSearchResults";

const { mockNavigate } = vi.hoisted(() => ({ mockNavigate: vi.fn() }));
vi.mock("react-router-dom", async (importOriginal) => {
  const mod = await importOriginal<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => mockNavigate };
});

function renderSearchBar() {
  const client = new QueryClient();
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiSearchBar repository="demo-repo" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

vi.mock("../../../hooks/useWikiSearch", () => ({
  useWikiSemanticSearch: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: true,
    error: null,
    data: {
      wiki_hits: [
        {
          page_path: "a/one",
          title: "First",
          snippet: "s1",
          score: 1,
          source: "wiki_fulltext",
        },
        {
          page_path: "b/two",
          title: "Second",
          snippet: "s2",
          score: 0.5,
          source: "wiki_fulltext",
        },
      ],
      entity_hits: [],
      call_chain_hits: [],
      total_count: 2,
    },
  }),
}));

describe("WikiSearchBar combobox a11y", () => {
  it("sets aria-activedescendant and aria-selected for keyboard highlight", () => {
    renderSearchBar();
    fireEvent.click(screen.getByRole("button", { name: /search wiki/i }));
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "q" } });
    const listId = "wiki-search-results-listbox";
    const opt0 = wikiSearchOptionId(listId, 0);
    const opt1 = wikiSearchOptionId(listId, 1);
    const options = () => screen.getAllByRole("option");
    expect(input).toHaveAttribute("aria-activedescendant", opt0);
    expect(options()[0]).toHaveAttribute("aria-selected", "true");
    expect(options()[1]).toHaveAttribute("aria-selected", "false");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input).toHaveAttribute("aria-activedescendant", opt1);
    expect(options()[0]).toHaveAttribute("aria-selected", "false");
    expect(options()[1]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input).toHaveAttribute("aria-activedescendant", opt0);
  });

  it("submits the active result on Enter", () => {
    mockNavigate.mockClear();
    renderSearchBar();
    fireEvent.click(screen.getByRole("button", { name: /search wiki/i }));
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "q" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(mockNavigate).toHaveBeenCalled();
    const href = String(mockNavigate.mock.calls[0]?.[0]);
    expect(href).toContain(encodeURIComponent("a/one"));
    expect(href).toContain("repo=demo-repo");
  });
});
