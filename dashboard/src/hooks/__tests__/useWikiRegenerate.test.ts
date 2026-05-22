import { type ReactNode, createElement } from "react";
import { renderHook, act, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useWikiRegenerate } from "../useWikiRegenerate";
import * as client from "../../api/client";
import en from "../../i18n/en";

const toast = vi.fn();

vi.mock("../../components/Toast", () => ({
  useToast: () => ({ toast }),
}));

const useI18nMock = vi.fn((): { locale: "en" | "zh"; t: typeof en; setLocale: ReturnType<typeof vi.fn> } => ({
  locale: "en",
  t: en,
  setLocale: vi.fn(),
}));
vi.mock("../../i18n/context", () => ({
  useI18n: () => useI18nMock(),
}));

vi.mock("../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../api/client")>();
  return {
    ...mod,
    businessWikiGenerate: vi.fn(),
    businessWikiTaskStatus: vi.fn(),
  };
});

function createWrapper() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

describe("useWikiRegenerate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useI18nMock.mockReturnValue({ locale: "en" as const, t: en, setLocale: vi.fn() });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns early and does not call the API for blank business id", async () => {
    const { result } = renderHook(() => useWikiRegenerate("   "), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.regenerate(true);
    });
    expect(vi.mocked(client.businessWikiGenerate)).not.toHaveBeenCalled();
  });

  it("uses success toast and invalidation when there is no task id", async () => {
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "",
      status: "done",
      mode: "full",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.regenerate(true);
    });
    expect(vi.mocked(client.businessWikiGenerate)).toHaveBeenCalledWith("biz-1", "en", true, "full");
    expect(toast).toHaveBeenCalledWith("success", en.wiki.regenerateStarted);
  });

  it("passes zh language when locale is zh", async () => {
    useI18nMock.mockReturnValue({ locale: "zh", t: en, setLocale: vi.fn() });
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "",
      status: "done",
      mode: "full",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.regenerate(true);
    });
    expect(vi.mocked(client.businessWikiGenerate)).toHaveBeenCalledWith("biz-1", "zh", true, "full");
  });

  it("polls until task completes and shows success", async () => {
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "task-1",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "task-1",
      status: "completed",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      const regen = result.current.regenerate(true);
      await vi.advanceTimersByTimeAsync(2000);
      await regen;
    });
    expect(vi.mocked(client.businessWikiTaskStatus)).toHaveBeenCalledWith("task-1");
    expect(toast).toHaveBeenCalledWith("success", en.wiki.regenerateComplete);
  });

  it("uses error.detail when failed status has object error with detail", async () => {
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "t-err-obj",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "t-err-obj",
      status: "failed",
      error: { error: "internal", detail: "code_10" },
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      const regen = result.current.regenerate(true);
      await vi.advanceTimersByTimeAsync(2000);
      await regen;
    });
    expect(toast).toHaveBeenCalledWith("error", en.wiki.regenerateFailed.replace("{detail}", "code_10"));
  });

  it("shows error toast when task fails with detail", async () => {
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "t2",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "t2",
      status: "failed",
      error: { detail: "boom" },
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    const p = act(async () => {
      await result.current.regenerate(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await p;
    expect(toast).toHaveBeenCalledWith("error", en.wiki.regenerateFailed.replace("{detail}", "boom"));
  });

  it("toasts timeout when max attempts are exhausted", async () => {
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "t3",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "t3",
      status: "running",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    const p = act(async () => {
      await result.current.regenerate(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000 * 120 + 10);
    });
    await p;
    expect(toast).toHaveBeenCalledWith(
      "error",
      "Wiki generation timed out. Please check status later.",
    );
  });

  it("toasts zh timeout message when locale is zh and max attempts exhausted", async () => {
    useI18nMock.mockReturnValue({ locale: "zh" as const, t: en, setLocale: vi.fn() });
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "t3-zh",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "t3-zh",
      status: "running",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    const p = act(async () => {
      await result.current.regenerate(true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000 * 120 + 10);
    });
    await p;
    expect(toast).toHaveBeenCalledWith("error", "Wiki 生成超时，请稍后检查状态");
  });

  it("uses unknown when task failed but error field is empty", async () => {
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "t-no-err",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "t-no-err",
      status: "failed",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      const regen = result.current.regenerate(true);
      await vi.advanceTimersByTimeAsync(2000);
      await regen;
    });
    expect(toast).toHaveBeenCalledWith(
      "error",
      en.wiki.regenerateFailed.replace("{detail}", en.common.unknown),
    );
  });

  it("toasts API errors via getErrorMessage", async () => {
    vi.mocked(client.businessWikiGenerate).mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.regenerate(true);
    });
    expect(toast).toHaveBeenCalledWith("error", "network down");
  });

  it("toasts conflict when businessWikiGenerate returns 409", async () => {
    vi.mocked(client.businessWikiGenerate).mockRejectedValue(
      new client.ApiError("Business wiki generation already running.", 409, {
        error: "generation_in_progress",
      }),
    );
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      await result.current.regenerate(true);
    });
    expect(toast).toHaveBeenCalledWith("error", en.wiki.regenerateConflict);
  });

  it("stops polling when task is cancelled during regenerate", async () => {
    vi.useFakeTimers();
    vi.mocked(client.businessWikiGenerate).mockResolvedValue({
      task_id: "task-cancel",
      status: "pending",
      mode: "full",
    });
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "task-cancel",
      status: "cancelled",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await act(async () => {
      const regen = result.current.regenerate(true);
      await vi.advanceTimersByTimeAsync(2000);
      await regen;
    });
    expect(localStorage.getItem("kb_wiki_active_task:biz-1")).toBeNull();
    expect(result.current.isPending).toBe(false);
    expect(result.current.progress).toBeNull();
    expect(vi.mocked(client.businessWikiTaskStatus)).toHaveBeenCalledTimes(1);
    expect(toast).toHaveBeenCalledWith("info", en.wiki.taskCancelled);
  });

  it("clears localStorage and resets state when resumed task is already cancelled", async () => {
    localStorage.setItem("kb_wiki_active_task:biz-1", "task-cancelled");
    vi.mocked(client.businessWikiTaskStatus).mockResolvedValue({
      task_id: "task-cancelled",
      status: "cancelled",
    });
    const { result } = renderHook(() => useWikiRegenerate("biz-1"), { wrapper: createWrapper() });
    await waitFor(() => {
      expect(result.current.isPending).toBe(false);
    });
    expect(localStorage.getItem("kb_wiki_active_task:biz-1")).toBeNull();
    expect(result.current.progress).toBeNull();
    expect(vi.mocked(client.businessWikiTaskStatus)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(client.businessWikiTaskStatus)).toHaveBeenCalledWith("task-cancelled");
  });
});
