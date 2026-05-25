import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import DeepResearchTimeline, { type StageEvent } from "../DeepResearchTimeline";
import { renderWithI18n } from "../../test/renderWithI18n";

const stages: StageEvent[] = [
  { type: "plan", data: {}, status: "done" },
  { type: "progress", data: { iteration: 0 }, status: "active" },
  { type: "search_done", data: { iteration: 0, result_count: 3 }, status: "done" },
  { type: "synthesis", data: { iteration: 0, sufficient: true }, status: "done" },
  { type: "conclusion", data: {}, status: "done" },
  { type: "error", data: { message: "timeout" }, status: "done" },
  { type: "planning", data: { round: 1, sub_queries: ["auth", "oauth"] }, status: "pending" },
  { type: "planning", data: { round: 2 }, status: "pending" },
  { type: "evaluating", data: { round: 1, score: 0.82 }, status: "pending" },
];

describe("DeepResearchTimeline", () => {
  it("returns null when stages are empty", () => {
    const { container } = renderWithI18n(<DeepResearchTimeline stages={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("renders stage rows for all event types", () => {
    renderWithI18n(<DeepResearchTimeline stages={stages} />);
    expect(screen.getByText(/timeout/i)).toBeInTheDocument();
    expect(screen.getByText(/auth, oauth/i)).toBeInTheDocument();
    expect(screen.getByText(/82%/)).toBeInTheDocument();
  });
});
