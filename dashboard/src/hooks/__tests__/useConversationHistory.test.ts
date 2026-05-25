import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useConversationHistory,
  save,
  list,
  get,
  remove,
  clear,
  type WikiStoredConversation,
} from "../useConversationHistory";

const conv: WikiStoredConversation = {
  id: "c1",
  title: "First",
  messages: [{ role: "user", content: "hello" }],
  created_at: Date.now(),
};

describe("conversation storage helpers", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("save/list/get round-trip", () => {
    save("repo-a", conv);
    expect(list("repo-a")).toHaveLength(1);
    expect(get("repo-a", "c1")?.title).toBe("First");
  });

  it("remove and clear mutate storage", () => {
    save("repo-a", conv);
    remove("repo-a", "c1");
    expect(list("repo-a")).toHaveLength(0);
    save("repo-a", conv);
    clear("repo-a");
    expect(list("repo-a")).toHaveLength(0);
  });
});

describe("useConversationHistory", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("exposes list/save/get/remove/clear callbacks", () => {
    const { result } = renderHook(() => useConversationHistory());
    act(() => {
      result.current.save("repo-b", conv);
    });
    expect(result.current.list("repo-b")).toHaveLength(1);
    expect(result.current.get("repo-b", "c1")?.title).toBe("First");
    act(() => {
      result.current.remove("repo-b", "c1");
    });
    expect(result.current.list("repo-b")).toHaveLength(0);
    act(() => {
      result.current.save("repo-b", conv);
      result.current.clear("repo-b");
    });
    expect(result.current.list("repo-b")).toHaveLength(0);
  });
});
