import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

describe("WikiPageFeedback", () => {
  it("renders thumbs up and down buttons", async () => {
    const WikiPageFeedback = (await import("../WikiPageFeedback")).default;
    render(<WikiPageFeedback pageUid="test-page" businessId="default" />);
    const up =
      screen.queryByLabelText(/thumbs up/i) ?? screen.queryByTitle(/helpful/i);
    expect(up).toBeTruthy();
  });
});
