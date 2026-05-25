import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import SyncSettingsPanel from "../SyncSettingsPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { ToastProvider } from "../../../components/Toast";
import { AuthProvider } from "../../../contexts/AuthContext";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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
          <SyncSettingsPanel />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("SyncSettingsPanel", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 1, git_url: "" }] }),
      ),
      http.get("/api/v1/sync/schedules", () =>
        HttpResponse.json({
          schedules: [
            {
              repo_name: "demo",
              git_url: "https://git.example.com/demo.git",
              branch: "main",
              interval_minutes: 60,
              enabled: true,
              last_sync_at: null,
              last_sync_status: "ok",
              last_sync_detail: "",
              created_at: "2026-01-01T00:00:00.000Z",
            },
          ],
          total: 1,
        }),
      ),
      http.put("/api/v1/sync/schedules/:repo", () => HttpResponse.json({ ok: true })),
      http.post("/api/v1/sync/schedules", () => HttpResponse.json({ ok: true })),
      http.delete("/api/v1/sync/schedules/:repo", () => HttpResponse.json({ ok: true })),
      http.post("/api/v1/sync/trigger/:repo", () => HttpResponse.json({ ok: true })),
    );
  });

  it("renders sync schedules table", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByText("demo")).toBeInTheDocument();
    });
  });

  it("opens add schedule modal and saves", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: /add schedule/i }));
    await user.selectOptions(screen.getAllByRole("combobox")[0]!, "demo");
    const textboxes = screen.getAllByRole("textbox");
    await user.type(textboxes.find((el) => (el as HTMLInputElement).value === "") ?? textboxes[1]!, "https://git.example.com/new.git");
    await user.click(screen.getByRole("button", { name: /^save$/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("edits existing schedule from table", async () => {
    const user = userEvent.setup();
    renderPanel();
    await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: /edit/i })[0]!);
    expect(screen.getByDisplayValue("demo")).toBeInTheDocument();
  });

  it("opens confirm dialog on delete and deletes on confirm", async () => {
    const user = userEvent.setup();
    let deletedRepo: string | undefined;
    server.use(
      http.delete("/api/v1/sync/schedules/:repo", ({ params }) => {
        deletedRepo = decodeURIComponent(params.repo as string);
        return HttpResponse.json({ ok: true });
      }),
    );
    renderPanel();
    await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());
    const deleteButtons = screen.getAllByRole("button", { name: /^delete$/i });
    await user.click(deleteButtons[deleteButtons.length - 1]!);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/demo/i)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(deletedRepo).toBe("demo"));
  });
});
