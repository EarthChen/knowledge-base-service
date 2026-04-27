import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAllSettings, useCategorySettings } from "../useSettings";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client }, children);
  };
}

describe("useAllSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads settings from /settings", async () => {
    vi.mocked(api).mockResolvedValue({ categories: {} });
    const { result } = renderHook(() => useAllSettings(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/settings");
  });
});

describe("useCategorySettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not fetch when category is empty", () => {
    const { result } = renderHook(() => useCategorySettings(""), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(vi.mocked(api)).not.toHaveBeenCalled();
  });

  it("fetches a category and encodes the path segment", async () => {
    vi.mocked(api).mockResolvedValue({ category: "db", settings: {} });
    const { result } = renderHook(() => useCategorySettings("a/b"), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith(`/settings/${encodeURIComponent("a/b")}`);
  });
});
