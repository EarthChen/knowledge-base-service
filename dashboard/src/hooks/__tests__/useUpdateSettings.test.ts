import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useDeleteSetting, useTestConnection, useUpdateSettings } from "../useUpdateSettings";
import { api } from "../../api/client";
import type { SettingsBatchUpdate } from "../settingsTypes";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

function buildClientWithSpy() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
  return { invalidateSpy, wrapper };
}

describe("useUpdateSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("PUTs settings batch and invalidates settings queries on success", async () => {
    vi.mocked(api).mockResolvedValue({ status: "ok", updated: "1" });
    const { invalidateSpy, wrapper } = buildClientWithSpy();
    const body: SettingsBatchUpdate = {
      settings: [{ key: "K", value: "v", category: "c" }],
    };
    const { result } = renderHook(() => useUpdateSettings(), { wrapper });
    result.current.mutate(body);
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/settings", {
      method: "PUT",
      body: JSON.stringify(body),
    });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["settings"] });
  });
});

describe("useDeleteSetting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("DELETEs a setting by key and invalidates settings", async () => {
    vi.mocked(api).mockResolvedValue({ status: "ok", key: "my.key" });
    const { invalidateSpy, wrapper } = buildClientWithSpy();
    const { result } = renderHook(() => useDeleteSetting(), { wrapper });
    result.current.mutate("my.key");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/settings/my.key", { method: "DELETE" });
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["settings"] });
  });
});

describe("useTestConnection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs test-connection with target in body", async () => {
    vi.mocked(api).mockResolvedValue({ status: "ok", target: "t", message: "fine" });
    const { wrapper } = buildClientWithSpy();
    const { result } = renderHook(() => useTestConnection(), { wrapper });
    result.current.mutate("https://db");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith("/settings/test-connection", {
      method: "POST",
      body: JSON.stringify({ target: "https://db" }),
    });
  });
});
