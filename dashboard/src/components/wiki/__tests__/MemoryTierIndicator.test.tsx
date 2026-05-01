import { screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import MemoryTierIndicator from "../MemoryTierIndicator";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("MemoryTierIndicator", () => {
  it("renders working tier label", () => {
    renderWithI18n(<MemoryTierIndicator tier={0} />);
    expect(screen.getByText(/working/i)).toBeInTheDocument();
  });

  it("exposes accessible tier name", () => {
    renderWithI18n(<MemoryTierIndicator tier={2} />);
    expect(screen.getByRole("img", { name: /memory tier: semantic/i })).toBeInTheDocument();
  });

  it("sets data-tier attribute", () => {
    const { container } = renderWithI18n(<MemoryTierIndicator tier={3} className="ml-1" />);
    expect(container.querySelector("[data-tier='3']")).toBeTruthy();
  });
});
