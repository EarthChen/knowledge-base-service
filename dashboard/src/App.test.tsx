import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "./i18n/context";
import { AuthProvider } from "./contexts/AuthContext";
import { BusinessProvider } from "./contexts/BusinessContext";
import { server } from "./test/mocks/server";

vi.mock("./pages/Overview", () => ({
  default: function CrashOverview() {
    throw new Error("overview crash");
  },
}));

import App from "./App";

function renderAppAt(path: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <I18nProvider>
          <AuthProvider>
            <BusinessProvider>
              <App />
            </BusinessProvider>
          </AuthProvider>
        </I18nProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("App", () => {
  it("wraps routes in ErrorBoundary so lazy route errors show fallback", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    server.use(
      http.get("/api/v1/health", () => HttpResponse.json({ status: "ok" })),
      http.get("/api/v1/auth/me", () =>
        HttpResponse.json({
          role: "admin",
          auth_enabled: false,
          business_id: null,
        }),
      ),
      http.get("/api/v1/businesses", () =>
        HttpResponse.json({
          businesses: [
            { id: "default", name: "Default", description: "", created_at: 0 },
          ],
          total: 1,
        }),
      ),
    );

    renderAppAt("/");

    expect(await screen.findByText("Something went wrong", { exact: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
