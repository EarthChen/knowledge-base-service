import { describe, it, expect, vi, beforeEach } from "vitest";
import { hasWikiEditorConflict } from "../useWikiEditingPresence";
import { api } from "../../api/client";

vi.mock("../../api/client", () => ({ api: vi.fn() }));

describe("hasWikiEditorConflict", () => {
  it("is false for null, empty, or other_active false", () => {
    expect(hasWikiEditorConflict(null)).toBe(false);
    expect(
      hasWikiEditorConflict({ editors: [], other_active: false, degraded: false }),
    ).toBe(false);
  });

  it("is true when other_active is true", () => {
    expect(
      hasWikiEditorConflict({ editors: [], other_active: true, degraded: false }),
    ).toBe(true);
  });
});

describe("useWikiEditingPresence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("POSTs heartbeat, GETs editors, and DELETEs on unmount", async () => {
    const { useWikiEditingPresence } = await import("../useWikiEditingPresence");
    const { renderHook, waitFor } = await import("@testing-library/react");
    vi.mocked(api).mockResolvedValue({ other_active: false, editors: [] });

    const { unmount } = renderHook(() => useWikiEditingPresence("uid-1"));

    await waitFor(() => {
      const methods = vi.mocked(api).mock.calls.map((c) => (c[1] as RequestInit | undefined)?.method);
      expect(methods).toContain("POST");
      expect(methods).toContain(undefined); // GET has no method in 2nd arg
    });
    expect(
      vi.mocked(api).mock.calls.some(
        (c) => String(c[0]).includes(encodeURIComponent("uid-1")) && c[0]?.toString().includes("editing"),
      ),
    ).toBe(true);
    expect(
      vi.mocked(api).mock.calls.some((c) => String(c[0]).includes("editors")),
    ).toBe(true);

    unmount();
    await waitFor(() => {
      expect(
        vi.mocked(api).mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "DELETE"),
      ).toBe(true);
    });
  });
});
