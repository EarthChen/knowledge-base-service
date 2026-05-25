import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WebhookSettingsPanel from "../WebhookSettingsPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { ToastProvider } from "../../../components/Toast";
import { AuthProvider } from "../../../contexts/AuthContext";
import { server } from "../../../test/mocks/server";

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(["auth-me"], { role: "admin", auth_enabled: false, business_id: null });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider>
          <WebhookSettingsPanel />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("WebhookSettingsPanel", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/hooks/config", () =>
        HttpResponse.json({
          enabled: false,
          debounce_seconds: 60,
          auto_update_branches: ["main"],
          providers: { github: { secret: "***configured***" } },
        }),
      ),
    );
  });

  it("renders webhook settings for admin", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText(/webhook/i)).toBeInTheDocument();
    });
  });
});
