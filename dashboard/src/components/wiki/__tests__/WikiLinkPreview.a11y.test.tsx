import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiLinkPreview from "../WikiLinkPreview";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { useWikiPageByPath } from "../../../hooks/useWikiPageByPath";

vi.mock("../../../hooks/useWikiPageByPath", () => ({
  useWikiPageByPath: vi.fn(),
}));

function renderLink() {
  const client = new QueryClient();
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <WikiLinkPreview path="page/x" businessId="b1" wikiLinkParams={{ business_id: "b1" }}>
          Link text
        </WikiLinkPreview>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(useWikiPageByPath).mockImplementation((_b, _p, opts) => {
    if (!opts?.enabled) {
      return { data: undefined, isLoading: false, isError: false, isSuccess: false, error: null } as any;
    }
    return {
      data: { title: "T", content: "Body content here", context: { repository: "r" } },
      isLoading: false,
      isError: false,
      isSuccess: true,
      error: null,
    } as any;
  });
});

describe("WikiLinkPreview a11y", () => {
  it("exposes a tooltip with role=tooltip and aria-describedby on focus", async () => {
    renderLink();
    const link = screen.getByRole("link", { name: "Link text" });
    expect(link).not.toHaveAttribute("aria-describedby");
    fireEvent.focus(link);
    await waitFor(() => {
      expect(screen.getByRole("tooltip")).toBeInTheDocument();
    });
    const tip = screen.getByRole("tooltip");
    const tipId = tip.getAttribute("id");
    expect(tipId).toBeTruthy();
    expect(link).toHaveAttribute("aria-describedby", tipId);
  });

  it("hides describedby when blur clears preview", async () => {
    renderLink();
    const link = screen.getByRole("link", { name: "Link text" });
    fireEvent.focus(link);
    await waitFor(() => {
      expect(screen.getByRole("tooltip")).toBeInTheDocument();
    });
    fireEvent.blur(link);
    await waitFor(() => {
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    });
    expect(link).not.toHaveAttribute("aria-describedby");
  });
});
