import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCheckpoint, useDeleteCheckpoint } from "../useCheckpoint";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useCheckpoint", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("fetches checkpoint for business id", async () => {
    const checkpoint = {
      business_id: "my-biz",
      db_path: "/tmp/checkpoint.db",
      last_modified: 1_700_000_000,
      size_bytes: 4096,
    };
    vi.mocked(api).mockResolvedValue({ checkpoint });

    const { result } = renderHook(() => useCheckpoint("my-biz"), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/my-biz/checkpoint");
    expect(result.current.data).toEqual(checkpoint);
  });

  it("does not fetch when business id is empty", () => {
    const { result } = renderHook(() => useCheckpoint(""), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });
});

describe("useDeleteCheckpoint", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("deletes checkpoint via DELETE", async () => {
    vi.mocked(api).mockResolvedValue(undefined);

    const { result } = renderHook(() => useDeleteCheckpoint("biz-1"), { wrapper: createWrapper() });

    await result.current.mutateAsync();

    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/biz-1/checkpoint", { method: "DELETE" });
  });
});
