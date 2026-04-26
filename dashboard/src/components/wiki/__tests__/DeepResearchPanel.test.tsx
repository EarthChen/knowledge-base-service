import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";

describe("DeepResearchPanel", () => {
  it("renders research input", async () => {
    const DeepResearchPanel = (await import("../DeepResearchPanel")).default;
    render(<DeepResearchPanel businessId="default" repository="test-repo" />);
    expect(screen.getByPlaceholderText(/research/i) || screen.getByRole("textbox")).toBeTruthy();
  });
});
