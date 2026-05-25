import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import CommandPalette from "../CommandPalette";
import { renderWithI18n } from "../../test/renderWithI18n";

vi.mock("../../api/hooks", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/hooks")>();
  return {
    ...mod,
    useHybridQuickSearch: () => ({
      data: {
        semantic_matches: [
          {
            uid: "fn-1",
            name: "searchHandler",
            type: "function",
            file: "src/search.ts",
            line: 1,
            score: 0.9,
          },
        ],
      },
      isFetching: false,
    }),
  };
});

function renderPalette() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("CommandPalette", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens via trigger button", () => {
    renderPalette();
    fireEvent.click(screen.getByRole("button", { name: /ctrl\+k/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
  });

  it("shows quick search results when open", async () => {
    renderPalette();
    fireEvent.click(screen.getByRole("button", { name: /ctrl\+k/i }));
    expect(await screen.findByText("searchHandler")).toBeInTheDocument();
  });
});
