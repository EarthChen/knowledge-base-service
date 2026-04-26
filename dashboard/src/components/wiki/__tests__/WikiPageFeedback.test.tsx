import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({ api: vi.fn() }));

describe("WikiPageFeedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders thumbs up and down buttons", async () => {
    const WikiPageFeedback = (await import("../WikiPageFeedback")).default;
    vi.mocked(api).mockResolvedValue(undefined);
    render(<WikiPageFeedback pageUid="test-page" businessId="default" />);
    const up =
      screen.queryByLabelText(/thumbs up/i) ?? screen.queryByTitle(/helpful/i);
    expect(up).toBeTruthy();
  });

  it("submits feedback via api client with auth", async () => {
    const userEvent = (await import("@testing-library/user-event")).default;
    const user = userEvent.setup();
    const WikiPageFeedback = (await import("../WikiPageFeedback")).default;
    vi.mocked(api).mockResolvedValue({ ok: true });
    render(<WikiPageFeedback pageUid="p1" businessId="biz-1" />);
    const up = screen.queryByLabelText(/thumbs up/i) ?? screen.queryByTitle(/helpful/i);
    expect(up).toBeTruthy();
    await user.click(up!);
    expect(vi.mocked(api)).toHaveBeenCalledWith("/wiki/pages/p1/feedback", {
      method: "POST",
      body: JSON.stringify({ rating: "up", business_id: "biz-1" }),
    });
  });
});
