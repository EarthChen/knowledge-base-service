import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ContradictionAlert } from "../ContradictionAlert";

describe("ContradictionAlert", () => {
  it("renders nothing when count is 0", () => {
    const { container } = render(<ContradictionAlert unresolvedCount={0} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows warning when count >= 1", () => {
    render(<ContradictionAlert unresolvedCount={2} summary="Mismatch on return type" />);
    expect(screen.getByText(/contradiction warning/i)).toBeInTheDocument();
    expect(screen.getByText(/2 open contradictions/i)).toBeInTheDocument();
    expect(screen.getByText(/Mismatch on return type/)).toBeInTheDocument();
  });
});
