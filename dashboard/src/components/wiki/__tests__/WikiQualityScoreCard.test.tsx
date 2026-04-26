import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import WikiQualityScoreCard from "../WikiQualityScoreCard";
import { renderWithI18n } from "../../../test/renderWithI18n";

const mockUseWikiQualityScore = vi.fn();

vi.mock("../../../hooks/useWikiQualityScore", () => ({
  useWikiQualityScore: (businessId: string) => mockUseWikiQualityScore(businessId),
}));

describe("WikiQualityScoreCard", () => {
  beforeEach(() => {
    mockUseWikiQualityScore.mockReset();
  });

  it("shows loading state", () => {
    mockUseWikiQualityScore.mockReturnValue({
      isLoading: true,
      isError: false,
      error: null,
      data: undefined,
    });
    renderWithI18n(<WikiQualityScoreCard businessId="biz1" />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("renders score and factor labels", () => {
    mockUseWikiQualityScore.mockReturnValue({
      isLoading: false,
      isError: false,
      error: null,
      data: {
        score: 72,
        factors: [
          { name: "coverage", weight: 0.4, score: 0.8 },
          { name: "staleness", weight: 0.3, score: 0.7 },
          { name: "reference_density", weight: 0.2, score: 0.6 },
          { name: "annotation_density", weight: 0.1, score: 0.5 },
        ],
        details: {},
      },
    });
    renderWithI18n(<WikiQualityScoreCard businessId="biz1" />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(mockUseWikiQualityScore).toHaveBeenCalledWith("biz1");
  });
});
