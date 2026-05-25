import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import WikiCoverageCard from "../wiki/WikiCoverageCard";
import { renderWithI18n } from "../../test/renderWithI18n";

vi.mock("react-chartjs-2", () => ({
  Doughnut: () => <div data-testid="coverage-chart" />,
}));

vi.mock("../../hooks/useWikiCoverage", () => ({
  useWikiCoverage: () => ({
    data: { covered_modules: 8, total_modules: 10, coverage_ratio: 0.8 },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("../../hooks/useIsDarkMode", () => ({
  useIsDarkMode: () => false,
}));

describe("WikiCoverageCard", () => {
  it("renders coverage stats and chart", () => {
    renderWithI18n(<WikiCoverageCard businessId="default" />);
    expect(screen.getByText(/wiki coverage/i)).toBeInTheDocument();
    expect(screen.getByTestId("coverage-chart")).toBeInTheDocument();
    expect(screen.getAllByText("80%").length).toBeGreaterThan(0);
  });
});
