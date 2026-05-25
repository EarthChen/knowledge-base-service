import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Indexing from "../Indexing";
import { renderWithI18n } from "../../test/renderWithI18n";
import { ToastProvider } from "../../components/Toast";
import { server } from "../../test/mocks/server";

vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "default",
    setCurrentBusiness: vi.fn(),
    businesses: [{ id: "default", name: "Default", description: "", created_at: 0 }],
    isLoading: false,
    isBound: true,
  }),
}));

vi.mock("../../hooks/useBusinessRepositories", () => ({
  useBusinessRepositories: () => ({
    data: { repositories: ["demo"] },
    isLoading: false,
    isFetched: true,
  }),
}));

function renderIndexing() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>
          <Indexing />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Indexing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/index/tasks", () =>
        HttpResponse.json({
          tasks: [
            {
              task_id: "task-1",
              status: "completed",
              mode: "full",
              directory: "/src",
              repository: "demo",
              created_at: "2026-01-01T00:00:00.000Z",
              progress: {
                phase: "completed",
                total_files: 10,
                processed_files: 10,
                enriched_count: 0,
              },
            },
          ],
        }),
      ),
      http.get("/api/v1/index/tasks/task-1", () =>
        HttpResponse.json({
          task_id: "task-1",
          status: "completed",
          mode: "full",
          directory: "/src",
          repository: "demo",
          created_at: "2026-01-01T00:00:00.000Z",
          progress: {
            phase: "completed",
            total_files: 10,
            processed_files: 10,
            enriched_count: 0,
          },
        }),
      ),
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 42, git_url: "" }] }),
      ),
      http.post("/api/v1/index/files", () =>
        HttpResponse.json({ task_id: "upload-1", status: "pending" }),
      ),
      http.get("/api/v1/index/tasks/upload-1", () =>
        HttpResponse.json({
          task_id: "upload-1",
          status: "running",
          mode: "full",
          directory: "uploaded",
          repository: "uploaded",
          created_at: "2026-01-01T00:00:00.000Z",
          progress: {
            phase: "indexing",
            total_files: 1,
            processed_files: 0,
            enriched_count: 0,
            stats: {},
          },
        }),
      ),
      http.post("/api/v1/index", () =>
        HttpResponse.json({ task_id: "task-new", status: "pending" }),
      ),
      http.post("/api/v1/enrich", () =>
        HttpResponse.json({ task_id: "enrich-1", status: "pending" }),
      ),
    );
  });

  it("renders indexing title and start button", async () => {
    renderIndexing();
    expect(screen.getByRole("heading", { name: /indexing/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start indexing/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText(/recent tasks/i)).toBeInTheDocument();
    });
  });

  it("shows upload panel and business context", () => {
    renderIndexing();
    expect(screen.getByText(/drop files here/i)).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
  });

  it("submits index form", async () => {
    const user = userEvent.setup();
    renderIndexing();

    const directoryInput = screen.getByPlaceholderText(/path\/to\/repository/i);
    await user.type(directoryInput, "/tmp/project");
    await user.click(screen.getByRole("button", { name: /start indexing/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /start indexing/i })).not.toBeDisabled();
    });
  });

  it("opens enrich modal", async () => {
    const user = userEvent.setup();
    renderIndexing();
    await user.click(screen.getByRole("button", { name: /enrichment/i }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("switches to incremental indexing mode", async () => {
    const user = userEvent.setup();
    renderIndexing();
    await user.click(screen.getByRole("radio", { name: /incremental/i }));
    expect(screen.getByLabelText(/base ref/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/head ref/i)).toBeInTheDocument();
  });

  it("uploads queued files and starts indexing task", async () => {
    const user = userEvent.setup();
    renderIndexing();
    const file = new File(["print(1)"], "main.py", { type: "text/plain" });
    await user.upload(screen.getByLabelText(/drop files here/i), file);
    expect(screen.getByText("main.py")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /upload & index/i }));
    await waitFor(() => expect(screen.getByText(/upload-1/i)).toBeInTheDocument());
  });

  it("shows task progress when viewing details", async () => {
    const user = userEvent.setup();
    renderIndexing();
    await waitFor(() => expect(screen.getByRole("button", { name: /view details/i })).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /view details/i }));
    expect(await screen.findByText(/task-1/i)).toBeInTheDocument();
  });

  it("submits enrich modal with selected repository", async () => {
    const user = userEvent.setup();
    renderIndexing();
    await user.click(screen.getByRole("button", { name: /enrichment/i }));
    await user.selectOptions(screen.getByRole("combobox"), "demo");
    await user.click(screen.getByRole("button", { name: /start enrichment/i }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });
});
