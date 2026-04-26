import { screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderWithI18n } from "../../../test/renderWithI18n";

vi.mock("../../../api/client", () => ({ api: vi.fn() }));

describe("DeepResearchPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders research input with i18n placeholder", async () => {
    const DeepResearchPanel = (await import("../DeepResearchPanel")).default;
    renderWithI18n(<DeepResearchPanel businessId="default" repository="test-repo" />);
    expect(
      screen.getByPlaceholderText("Ask a deep research question…"),
    ).toBeInTheDocument();
  });
});
