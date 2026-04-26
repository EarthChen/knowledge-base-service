import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ConfidenceBadge } from "../ConfidenceBadge";

describe("ConfidenceBadge", () => {
  it("shows high label when score >= 0.8", () => {
    render(<ConfidenceBadge score={0.85} />);
    expect(screen.getByText(/high confidence/i)).toBeInTheDocument();
  });

  it("shows medium for scores between 0.5 and 0.8", () => {
    render(<ConfidenceBadge score={0.64} />);
    expect(screen.getByText(/medium/i)).toBeInTheDocument();
  });

  it("shows low confidence when score < 0.5", () => {
    render(<ConfidenceBadge score={0.1} />);
    expect(screen.getByText(/low confidence/i)).toBeInTheDocument();
  });
});
