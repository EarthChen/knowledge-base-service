import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { WikiVersionPicker } from "../WikiContent";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { useWikiVersions } from "../../../hooks/useWikiVersions";

vi.mock("../../../hooks/useWikiVersions", () => ({
  useWikiVersions: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(useWikiVersions).mockReturnValue({
    data: [
      {
        version: 1,
        content_hash: "abc",
        change_summary: "",
        generated_at: "2026-01-01T00:00:00Z",
      },
    ],
    isLoading: false,
  } as ReturnType<typeof useWikiVersions>);
});

function renderPicker() {
  const client = new QueryClient();
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <WikiVersionPicker businessId="biz-1" pageUid="uid-1" version="1" generatedAt="2026-01-01" />
    </QueryClientProvider>,
  );
}

describe("WikiVersionPicker a11y", () => {
  it("closes the popover on Escape via FocusTrap", async () => {
    renderPicker();
    const badge = screen.getByRole("button", { name: /v1/i });
    fireEvent.click(badge);
    expect(await screen.findByText("Version history")).toBeInTheDocument();
    await waitFor(() => {
      expect(document.activeElement).toBeInstanceOf(HTMLElement);
    });
    const focused = document.activeElement as HTMLElement;
    fireEvent.keyDown(focused, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByText("Version history")).not.toBeInTheDocument();
    });
  });
});
