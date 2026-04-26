import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useBusinessFlows } from "../useBusinessFlows";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useBusinessFlows", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads flows via api client", async () => {
    vi.mocked(api).mockResolvedValue({
      nodes: [{ uid: "a", title: "A" }],
      edges: [],
    });
    const { result } = renderHook(() => useBusinessFlows("my-biz"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      nodes: [{ uid: "a", title: "A" }],
      edges: [],
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/flows?business_id=my-biz");
  });

  it("does not suppress HTTP errors", async () => {
    vi.mocked(api).mockRejectedValue(new Error("Failed to fetch flows: 500"));
    const { result } = renderHook(() => useBusinessFlows("x"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toBe("Failed to fetch flows: 500");
  });
});
