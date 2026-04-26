import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import WikiGenerationProgress from "../WikiGenerationProgress";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiGenerationProgress a11y", () => {
  it("announces status with role=status and aria-live=polite", () => {
    renderWithI18n(<WikiGenerationProgress status="wiki:generation_started" />);
    const el = screen.getByRole("status");
    expect(el).toHaveAttribute("aria-live", "polite");
  });
});
