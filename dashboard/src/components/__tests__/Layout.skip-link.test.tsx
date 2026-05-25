import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Layout from "../Layout";
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

vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => ({
    authError: false,
  }),
}));

vi.mock("../CommandPalette", () => ({
  default: () => null,
}));

vi.mock("../FocusTrap", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function renderLayout() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderWithI18n(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Layout skip link", () => {
  it("renders a skip-to-content link that targets main content", () => {
    renderLayout();
    const skipLink = screen.getByRole("link", { name: /skip to main content/i });
    expect(skipLink).toHaveAttribute("href", "#main-content");
  });

  it("skip link is focusable", () => {
    renderLayout();
    const skipLink = screen.getByRole("link", { name: /skip to main content/i });
    skipLink.focus();
    expect(document.activeElement).toBe(skipLink);
  });

  it("main landmark has id main-content", () => {
    renderLayout();
    expect(document.getElementById("main-content")).toBeInstanceOf(HTMLElement);
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
  });

  it("does not render an h1 in the layout header", () => {
    renderLayout();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });
});
