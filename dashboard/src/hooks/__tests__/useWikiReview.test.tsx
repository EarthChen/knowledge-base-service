import type { ReactNode } from "react";
import { createElement } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useBatchReview, useRegeneratePage, useSetPageReview } from "../useWikiReview";
import { ApiError, api } from "../../api/client";
import { TestI18nProvider } from "../../i18n/context";
import en from "../../i18n/en";

const toast = vi.fn();
vi.mock("../../components/Toast", () => ({
  useToast: () => ({ toast }),
}));

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return { ...mod, api: vi.fn() };
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Provider({ children }: { children: ReactNode }) {
    return createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(TestI18nProvider, { locale: "en" }, children),
    );
  }
  Provider.displayName = "TestWikiReviewWrapper";
  return Provider;
}

describe("useSetPageReview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockResolvedValue({});
  });

  it("sends POST with encoded path and JSON body status and notes", async () => {
    const { result } = renderHook(() => useSetPageReview(), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.mutateAsync({
        pagePath: "topics/a/page",
        status: "approved",
        notes: "lgtm",
      });
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith(`/wiki/pages/${encodeURIComponent("topics/a/page")}/review`, {
      method: "POST",
      body: JSON.stringify({ status: "approved", notes: "lgtm" }),
    });
  });

  it("toasts error on failure via getErrorMessage", async () => {
    vi.mocked(api).mockRejectedValueOnce(new ApiError("bad", 400, null));

    const { result } = renderHook(() => useSetPageReview(), { wrapper: createWrapper() });

    await act(async () => {
      try {
        await result.current.mutateAsync({ pagePath: "/x", status: "pending", notes: "" });
      } catch {
        /* mutation surfaces error */
      }
    });

    expect(toast).toHaveBeenCalledWith("error", "bad");
  });
});

describe("useBatchReview", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockResolvedValue({});
  });

  it("POSTs wiki/review/batch with business_id and reviews", async () => {
    const reviews = [{ page_path: "/a", status: "approved", notes: "ok" }] as const;
    const { result } = renderHook(() => useBatchReview(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.mutateAsync({ businessId: "biz-1", reviews: [...reviews] });
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/review/batch", {
      method: "POST",
      body: JSON.stringify({ business_id: "biz-1", reviews: [...reviews] }),
    });
  });

  it("toasts unexpected error message when rejection has empty message", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error(""));

    const { result } = renderHook(() => useBatchReview(), { wrapper: createWrapper() });

    await act(async () => {
      try {
        await result.current.mutateAsync({ businessId: "b", reviews: [] });
      } catch {
        /* surface */
      }
    });

    expect(toast).toHaveBeenCalledWith("error", en.common.unexpectedError);
  });
});

describe("useRegeneratePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api).mockResolvedValue({ task_id: "t-1" });
  });

  it("POSTs heal_hints in body defaulting empty string when healHints omitted", async () => {
    const { result } = renderHook(() => useRegeneratePage(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.mutateAsync({ pagePath: "wiki/foo.md" });
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith(`/wiki/pages/${encodeURIComponent("wiki/foo.md")}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ heal_hints: "" }),
    });
  });

  it("includes heal_hints when provided", async () => {
    const { result } = renderHook(() => useRegeneratePage(), { wrapper: createWrapper() });

    await act(async () => {
      await result.current.mutateAsync({ pagePath: "p.md", healHints: "fix links" });
    });

    expect(vi.mocked(api)).toHaveBeenCalledWith(`/wiki/pages/${encodeURIComponent("p.md")}/regenerate`, {
      method: "POST",
      body: JSON.stringify({ heal_hints: "fix links" }),
    });
  });

  it("toasts error when regenerate fails", async () => {
    vi.mocked(api).mockRejectedValueOnce(new Error("boom"));

    const { result } = renderHook(() => useRegeneratePage(), { wrapper: createWrapper() });

    await act(async () => {
      try {
        await result.current.mutateAsync({ pagePath: "/" });
      } catch {
        /* surface */
      }
    });

    expect(toast).toHaveBeenCalledWith("error", "boom");
  });
});
