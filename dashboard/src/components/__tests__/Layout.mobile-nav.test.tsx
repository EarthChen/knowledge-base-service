import { describe, it, expect, vi, beforeEach, afterEach, type ReactNode } from "vitest";
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

const focusTrapMock = vi.fn(
  ({ children, onEscape }: { children: ReactNode; onEscape?: () => void }) => (
    <div
      data-testid="mobile-nav-focus-trap"
      tabIndex={-1}
      onKeyDown={(e) => {
        if (e.key === "Escape") onEscape?.();
      }}
    >
      {children}
    </div>
  ),
);

vi.mock("../FocusTrap", () => ({
  default: (props: { children: ReactNode; onEscape?: () => void }) => focusTrapMock(props),
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

describe("Layout mobile nav FocusTrap", () => {
  beforeEach(() => {
    focusTrapMock.mockClear();
    vi.spyOn(window, "innerWidth", "get").mockReturnValue(375);
    window.dispatchEvent(new Event("resize"));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses i18n toggleMenu label on mobile menu button", () => {
    renderLayout();
    expect(screen.getByRole("button", { name: "Toggle menu" })).toBeInTheDocument();
  });

  it("renders FocusTrap when mobile sidebar is open", async () => {
    const user = userEvent.setup();
    renderLayout();
    expect(screen.queryByTestId("mobile-nav-focus-trap")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Toggle menu" }));
    expect(screen.getByTestId("mobile-nav-focus-trap")).toBeInTheDocument();
    expect(focusTrapMock).toHaveBeenCalledWith(
      expect.objectContaining({ onEscape: expect.any(Function) }),
    );
  });

  it("closes mobile sidebar on Escape via FocusTrap", async () => {
    const user = userEvent.setup();
    renderLayout();
    await user.click(screen.getByRole("button", { name: "Toggle menu" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    screen.getByTestId("mobile-nav-focus-trap").focus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
