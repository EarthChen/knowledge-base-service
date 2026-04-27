import { type ReactNode, createElement } from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { usePatchWikiPage } from "../useWikiPageEdit";
import { api } from "../../api/client";

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

describe("usePatchWikiPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("PATCHes content with edit reason and expected version, then invalidates wiki queries", async () => {
    vi.mocked(api).mockResolvedValue({ ok: true, version: 3 });
    const { invalidateSpy, wrapper } = buildClientWithSpy();
    const { result } = renderHook(() => usePatchWikiPage(), { wrapper });
    result.current.mutate({
      pageUid: "some/uid",
      content: "body",
      editReason: "typo",
      expectedVersion: 2,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/pages/${encodeURIComponent("some/uid")}/content`,
      {
        method: "PATCH",
        body: JSON.stringify({
          content: "body",
          edit_reason: "typo",
          expected_version: 2,
        }),
      },
    );
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["wiki"] });
  });

  it("defaults edit_reason to empty string and expected_version to null when omitted", async () => {
    vi.mocked(api).mockResolvedValue({ ok: true });
    const { wrapper } = buildClientWithSpy();
    const { result } = renderHook(() => usePatchWikiPage(), { wrapper });
    result.current.mutate({ pageUid: "x", content: "c" });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      `/wiki/pages/${encodeURIComponent("x")}/content`,
      {
        method: "PATCH",
        body: JSON.stringify({
          content: "c",
          edit_reason: "",
          expected_version: null,
        }),
      },
    );
  });
});
