import { describe, it, expect, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import FileExplorer from "../FileExplorer";
import { renderWithI18n } from "../../test/renderWithI18n";
import { server } from "../../test/mocks/server";

function renderFileExplorer() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FileExplorer />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("FileExplorer", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 10, git_url: "" }] }),
      ),
      http.get("/api/v1/files/tree", () =>
        HttpResponse.json({
          type: "dir",
          name: "demo",
          path: "",
          repository: "demo",
          children: [
            { type: "file", name: "main.py", path: "main.py", repository: "demo" },
          ],
        }),
      ),
      http.get("/api/v1/files/content", () =>
        HttpResponse.json({
          content: "print('hi')\n",
          start_line: 1,
          file_path: "main.py",
          total_lines: 1,
          truncated: false,
        }),
      ),
      http.get("/api/v1/files/entities", () =>
        HttpResponse.json({ entities: [{ name: "hello", start_line: 1, entity_type: "function" }] }),
      ),
    );
  });

  it("renders file explorer title and filter input", async () => {
    renderFileExplorer();
    expect(screen.getByRole("heading", { name: /file explorer/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/filter by file/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("main.py")).toBeInTheDocument());
  });

  it("loads file content when selecting a file", async () => {
    const user = userEvent.setup();
    renderFileExplorer();
    await waitFor(() => expect(screen.getByText("main.py")).toBeInTheDocument());
    await user.click(screen.getByText("main.py"));
    expect(await screen.findByText("main.py", { selector: "p" })).toBeInTheDocument();
    expect(await screen.findByText("hello")).toBeInTheDocument();
  });

  it("filters file tree via search input", async () => {
    const user = userEvent.setup();
    renderFileExplorer();
    await waitFor(() => expect(screen.getByText("main.py")).toBeInTheDocument());
    await user.type(screen.getByPlaceholderText(/filter by file/i), "nomatch");
    expect(screen.queryByText("main.py")).not.toBeInTheDocument();
  });

  it("exposes tree ARIA roles on the file tree", async () => {
    renderFileExplorer();
    await waitFor(() => expect(screen.getByText("main.py")).toBeInTheDocument());
    expect(screen.getByRole("tree")).toBeInTheDocument();
    expect(screen.getAllByRole("treeitem").length).toBeGreaterThan(0);
  });

  it("sets aria-expanded on directory toggle buttons", async () => {
    server.use(
      http.get("/api/v1/files/tree", () =>
        HttpResponse.json({
          type: "dir",
          name: "demo",
          path: "",
          repository: "demo",
          children: [
            {
              type: "directory",
              name: "src",
              path: "src",
              repository: "demo",
              children: [{ type: "file", name: "main.py", path: "src/main.py", repository: "demo" }],
            },
          ],
        }),
      ),
    );
    renderFileExplorer();
    await waitFor(() => expect(screen.getByText("src")).toBeInTheDocument());
    const folderToggle = screen.getByRole("button", { name: /src/i });
    expect(folderToggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.setup().click(folderToggle);
    expect(folderToggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("group")).toBeInTheDocument();
  });
});
