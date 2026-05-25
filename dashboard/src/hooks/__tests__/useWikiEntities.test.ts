import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  encodeWikiPagePathForUrl,
  fetchWikiPageEntities,
  useWikiEntities,
} from "../useWikiEntities";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useWikiEntities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("encodeWikiPagePathForUrl encodes segments", () => {
    expect(encodeWikiPagePathForUrl("/auth/login")).toBe("auth/login");
  });

  it("fetchWikiPageEntities calls encoded wiki entities endpoint", async () => {
    vi.mocked(api).mockResolvedValue({ entities: [] });
    await fetchWikiPageEntities("default", "/auth");
    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/pages/auth/entities?business_id=default");
  });

  it("useWikiEntities fetches when page path and business id are set", async () => {
    vi.mocked(api).mockResolvedValue({
      entities: [{ name: "Svc", entity_type: "class", file_path: "a.py", repository: "demo" }],
    });
    const { result } = renderHook(() => useWikiEntities("/auth", "default"), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.entities[0]?.name).toBe("Svc");
  });
});
