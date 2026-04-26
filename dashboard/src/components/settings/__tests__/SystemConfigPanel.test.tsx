import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import SystemConfigPanel from "../SystemConfigPanel";
import { TestI18nProvider } from "../../../i18n/context";
import { ToastProvider } from "../../Toast";
import { server } from "../../../test/mocks/server";
import { mockSettingsResponse } from "../../../test/mocks/handlers";
import type { SettingsResponse } from "../../../hooks/settingsTypes";

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <TestI18nProvider>
        <ToastProvider>
          <SystemConfigPanel />
        </ToastProvider>
      </TestI18nProvider>
    </QueryClientProvider>,
  );
}

describe("SystemConfigPanel", () => {
  it("renders loading state", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });

    server.use(
      http.get("/api/v1/settings", async () => {
        await gate;
        return HttpResponse.json(mockSettingsResponse);
      }),
    );

    renderPanel();

    expect(document.querySelectorAll(".animate-pulse").length).toBeGreaterThan(0);

    release();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /wiki features/i })).toBeInTheDocument();
    });
  });

  it("renders category cards", async () => {
    renderPanel();

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /wiki features/i })).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: /wiki generation/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /wiki git/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^llm$/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /storage/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /embedding/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^system$/i })).toBeInTheDocument();
  });

  it("tracks dirty state", async () => {
    const user = userEvent.setup();
    renderPanel();

    const treeToggle = await screen.findByRole("checkbox", { name: /tree enabled/i });
    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();

    await user.click(treeToggle);

    expect(await screen.findByRole("button", { name: /save changes \(1\)/i })).toBeInTheDocument();
  });

  it("saves changes", async () => {
    const user = userEvent.setup();
    const putSpy = vi.fn();

    const initiallyOn: SettingsResponse = {
      categories: {
        wiki_features: {
          "wiki.tree_enabled": { value: "true", source: "db", sensitive: false },
        },
      },
    };

    server.use(
      http.get("/api/v1/settings", () => HttpResponse.json(initiallyOn)),
      http.put("/api/v1/settings", async ({ request }) => {
        putSpy(await request.json());
        return HttpResponse.json({ status: "ok", updated: "1" });
      }),
    );

    renderPanel();

    const treeToggle = await screen.findByRole("checkbox", { name: /tree enabled/i });
    expect(treeToggle).toBeChecked();
    await user.click(treeToggle);

    const saveBtn = await screen.findByRole("button", { name: /save changes \(1\)/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(putSpy).toHaveBeenCalled();
    });

    const body = putSpy.mock.calls[0][0] as { settings: Array<{ key: string; value: string }> };
    expect(body.settings).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: "wiki.tree_enabled",
          value: "false",
        }),
      ]),
    );
  });

  it("shows source badges", async () => {
    const withSources: SettingsResponse = {
      categories: {
        wiki_features: {
          "wiki.tree_enabled": { value: "true", source: "db", sensitive: false },
          "wiki.dual_view_enabled": { value: "false", source: "env", sensitive: false },
          "wiki.cross_reference_enabled": { value: "true", source: "default", sensitive: false },
        },
      },
    };

    server.use(http.get("/api/v1/settings", () => HttpResponse.json(withSources)));

    renderPanel();

    await waitFor(() => {
      expect(screen.getByText("db")).toBeInTheDocument();
    });
    expect(screen.getByText("env")).toBeInTheDocument();
    expect(screen.getByText("default")).toBeInTheDocument();
  });
});
