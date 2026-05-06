import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiSearchBar from "../WikiSearchBar";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { wikiSearchOptionId } from "../WikiSearchResults";
import type { WikiSearchResult } from "../../../hooks/wikiTypes";

const { mockNavigate } = vi.hoisted(() => ({ mockNavigate: vi.fn() }));
vi.mock("react-router-dom", async (importOriginal) => {
  const mod = await importOriginal<typeof import("react-router-dom")>();
  return { ...mod, useNavigate: () => mockNavigate };
});

const results: WikiSearchResult[] = [
  {
    page_path: "a/one",
    title: "First",
    score: 1,
    snippet: "s1",
    source_locations: [],
    context: {},
  },
  {
    page_path: "b/two",
    title: "Second",
    score: 0.5,
    snippet: "s2",
    source_locations: [],
    context: {},
  },
];

function renderSearchBar() {
  const client = new QueryClient();
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiSearchBar />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

vi.mock("../../../hooks/useWikiGlobalSearch", () => ({
  useWikiGlobalSearch: () => ({
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    isSuccess: true,
    error: null,
    data: {
      results,
      total: 2,
      query_expansion: {},
      by_repository: {},
      repositories_searched: [],
      partial_errors: [],
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
  });
});
