import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import GraphExplorer from "../GraphExplorer";
import { renderWithI18n } from "../../test/renderWithI18n";
import { server } from "../../test/mocks/server";

vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<typeof import("@xyflow/react")>("@xyflow/react");
  return {
    ...actual,
    ReactFlow: ({ children }: { children?: React.ReactNode }) => (
      <div data-testid="react-flow">{children}</div>
    ),
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
    Panel: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  };
});

function renderGraphExplorer() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GraphExplorer />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("GraphExplorer", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 10, git_url: "" }] }),
      ),
      http.post("/api/v1/graph/explore", () =>
        HttpResponse.json({
          nodes: [
            {
              id: "n1",
              name: "main",
              type: "function",
              properties: { name: "main", file: "main.py" },
            },
          ],
          edges: [],
        }),
      ),
      http.get("/api/v1/wiki/path-for-entity", () => HttpResponse.json({ path: null })),
    );
  });

  it("renders explorer title and search form", () => {
    renderGraphExplorer();
    expect(screen.getByRole("heading", { name: /graph explorer/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /explore/i })).toBeInTheDocument();
  });

  it("submits explore and renders graph canvas", async () => {
    const user = userEvent.setup();
    renderGraphExplorer();
    await user.type(screen.getByPlaceholderText(/enter function/i), "main");
    await user.click(screen.getByRole("button", { name: /explore/i }));
    await waitFor(() => expect(screen.getByTestId("react-flow")).toBeInTheDocument());
  });
});
