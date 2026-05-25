import { type ReactNode, type FormEvent, createElement } from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useGraphExplorerState } from "../useGraphExplorerState";
import { TestI18nProvider } from "../../../i18n/context";
import { server } from "../../../test/mocks/server";

function createWrapper(initial = "/graph") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(
      TestI18nProvider,
      null,
      createElement(
        QueryClientProvider,
        { client },
        createElement(MemoryRouter, { initialEntries: [initial] }, children),
      ),
    );
  };
}

describe("useGraphExplorerState", () => {
  beforeEach(() => {
    server.use(
      http.get("/api/v1/repositories", () =>
        HttpResponse.json({ repositories: [{ repository: "demo", nodes: 1, git_url: "" }] }),
      ),
      http.post("/api/v1/graph/explore", () =>
        HttpResponse.json({
          nodes: [{ id: "n1", name: "main", type: "function", properties: { name: "main" } }],
          edges: [],
        }),
      ),
    );
  });

  it("initializes search fields from URL", () => {
    const { result } = renderHook(() => useGraphExplorerState(), {
      wrapper: createWrapper("/graph?q=main"),
    });
    expect(result.current.searchName).toBe("main");
  });

  it("explore submit populates graph nodes", async () => {
    const { result } = renderHook(() => useGraphExplorerState(), { wrapper: createWrapper() });

    act(() => {
      result.current.setSearchName("main");
    });

    act(() => {
      result.current.handleSubmit({ preventDefault: () => {} } as FormEvent);
    });

    await waitFor(() => expect(result.current.nodes.length).toBeGreaterThan(0));
  });
});
