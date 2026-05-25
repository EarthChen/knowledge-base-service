import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import GeneralSettingsPanel from "../GeneralSettingsPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { ToastProvider } from "../../../components/Toast";
import { server } from "../../../test/mocks/server";

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <GeneralSettingsPanel />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("GeneralSettingsPanel", () => {
  beforeEach(() => {
    server.use(http.get("/api/v1/health", () => HttpResponse.json({ status: "ok" })));
  });

  it("renders language and API token sections", async () => {
    renderPanel();
    expect(screen.getByText(/language/i)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/api token/i)).toBeInTheDocument();
    });
  });

  it("toggles token visibility and saves API token", async () => {
    const user = userEvent.setup();
    renderPanel();
    const tokenInput = screen.getByPlaceholderText(/enter api token/i);
    expect(tokenInput).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: /show api token/i }));
    expect(tokenInput).toHaveAttribute("type", "text");
    await user.type(tokenInput, "secret-token");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(screen.getByText(/healthy/i)).toBeInTheDocument());
  });
});
