import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient } from "@tanstack/react-query";
import { STALE_TIME } from "../cacheConfig";
import { GC_TIME, appQueryClientDefaultOptions } from "../queryClientConfig";
import { registerGlobalToast } from "../../components/Toast";

describe("appQueryClientDefaultOptions", () => {
  beforeEach(() => {
    registerGlobalToast(() => {});
  });

  it("sets staleTime, gcTime, and mutation error handler defaults", () => {
    const client = new QueryClient({ defaultOptions: appQueryClientDefaultOptions });
    const options = client.getDefaultOptions();

    expect(options.queries?.staleTime).toBe(STALE_TIME.FAST);
    expect(options.queries?.gcTime).toBe(GC_TIME);
    expect(options.queries?.gcTime).toBe(300_000);
    expect(options.mutations?.onError).toBeTypeOf("function");
  });

  it("mutation onError calls global toast with error message", () => {
    const toast = vi.fn();
    registerGlobalToast(toast);
    const client = new QueryClient({ defaultOptions: appQueryClientDefaultOptions });
    const onError = client.getDefaultOptions().mutations?.onError;
    expect(onError).toBeTypeOf("function");
    onError?.(new Error("save failed"));
    expect(toast).toHaveBeenCalledWith("error", "save failed");
  });
});
