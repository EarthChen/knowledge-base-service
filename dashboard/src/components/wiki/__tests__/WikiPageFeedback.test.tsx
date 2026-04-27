import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../../../api/client";
import { TestI18nProvider } from "../../../i18n/context";

vi.mock("../../../api/client", () => ({ api: vi.fn() }));

describe("WikiPageFeedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders thumbs up and down buttons", async () => {
    const WikiPageFeedback = (await import("../WikiPageFeedback")).default;
    vi.mocked(api).mockResolvedValue(undefined);
    render(
      <TestI18nProvider>
        <WikiPageFeedback pageUid="test-page" businessId="default" />
      </TestI18nProvider>,
    );
    const up = screen.getByRole("button", { name: "Helpful" });
    expect(up).toBeTruthy();
  });

  it("submits feedback via api client with auth", async () => {
    const userEvent = (await import("@testing-library/user-event")).default;
    const user = userEvent.setup();
    const WikiPageFeedback = (await import("../WikiPageFeedback")).default;
    vi.mocked(api).mockResolvedValue({ ok: true });
    render(
      <TestI18nProvider>
        <WikiPageFeedback pageUid="p1" businessId="biz-1" />
      </TestI18nProvider>,
    );
    const up = screen.getByRole("button", { name: "Helpful" });
    expect(up).toBeTruthy();
    await user.click(up!);
    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/pages/p1/feedback", {
      method: "POST",
      body: JSON.stringify({ rating: "up", business_id: "biz-1" }),
    });
  });
});
