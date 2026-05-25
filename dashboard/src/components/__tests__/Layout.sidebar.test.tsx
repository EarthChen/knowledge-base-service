import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderWithI18n } from "../../test/renderWithI18n";

vi.mock("../../api/hooks", () => ({
  useHealth: () => ({ data: { status: "ok" } }),
}));

vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "test",
    businesses: [{ id: "test", name: "Test" }],
    isBound: true,
    setCurrentBusiness: vi.fn(),
  }),
}));

vi.mock("../CommandPalette", () => ({
  default: () => null,
}));

import Layout from "../Layout";

function renderLayout() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Mobile sidebar accessibility", () => {
  beforeEach(() => {
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(375);
    window.dispatchEvent(new Event("resize"));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("overlay has role=dialog and aria-modal", async () => {
    const user = userEvent.setup();
    renderLayout();
    await user.click(screen.getByRole("button", { name: "Toggle menu" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveAttribute("aria-label", "Navigation");
  });

  it("closes on Escape key", async () => {
    const user = userEvent.setup();
    renderLayout();
    await user.click(screen.getByRole("button", { name: "Toggle menu" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
