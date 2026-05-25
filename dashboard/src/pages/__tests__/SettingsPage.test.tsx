import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import SettingsPage from "../SettingsPage";
import { renderWithI18n } from "../../test/renderWithI18n";
import { ToastProvider } from "../../components/Toast";
import { AuthProvider } from "../../contexts/AuthContext";
import { server } from "../../test/mocks/server";

vi.mock("react-chartjs-2", () => ({
  Bar: () => <div data-testid="mock-chart" />,
  Doughnut: () => <div data-testid="mock-chart" />,
}));

function renderSettings() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(["auth-me"], { role: "admin", auth_enabled: false, business_id: null });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>
          <MemoryRouter>
            <SettingsPage />
          </MemoryRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("SettingsPage", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/health", () => HttpResponse.json({ status: "ok" })),
      http.get("/api/v1/hooks/config", () =>
        HttpResponse.json({
          enabled: false,
          debounce_seconds: 60,
          auto_update_branches: [],
          providers: {},
        }),
      ),
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 1, git_url: "" }] }),
      ),
      http.get("/api/v1/sync/schedules", () =>
        HttpResponse.json({
          schedules: [],
          total: 0,
        }),
      ),
      http.get("/api/v1/settings", () => HttpResponse.json({ categories: {} })),
    );
  });

  it("renders settings title and general tab content", async () => {
    renderSettings();
    expect(screen.getByRole("heading", { name: /settings/i })).toBeInTheDocument();
    expect(await screen.findByText(/language/i)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /webhook configuration/i })).toBeInTheDocument();
  });

  it("switches to system config tab", async () => {
    const user = userEvent.setup();
    renderSettings();

    await user.click(screen.getByRole("tab", { name: /system config/i }));
    expect(await screen.findByRole("heading", { name: /wiki features/i })).toBeInTheDocument();
  });

  it("ArrowRight moves focus to the next tab and activates it", async () => {
    renderSettings();
    const tablist = screen.getByRole("tablist");
    const generalTab = screen.getByRole("tab", { name: /general/i });
    generalTab.focus();
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    const systemTab = screen.getByRole("tab", { name: /system config/i });
    expect(document.activeElement).toBe(systemTab);
    expect(systemTab).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("heading", { name: /wiki features/i })).toBeInTheDocument();
  });

  it("ArrowLeft wraps focus to the previous tab", async () => {
    renderSettings();
    const tablist = screen.getByRole("tablist");
    const generalTab = screen.getByRole("tab", { name: /general/i });
    generalTab.focus();
    fireEvent.keyDown(tablist, { key: "ArrowLeft" });
    const systemTab = screen.getByRole("tab", { name: /system config/i });
    expect(document.activeElement).toBe(systemTab);
    expect(systemTab).toHaveAttribute("aria-selected", "true");
  });
});
