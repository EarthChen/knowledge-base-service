import { screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ContradictionAlert } from "../ContradictionAlert";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("ContradictionAlert", () => {
  it("renders nothing when count is 0", () => {
    const { container } = renderWithI18n(<ContradictionAlert unresolvedCount={0} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows warning when count >= 1", () => {
    renderWithI18n(<ContradictionAlert unresolvedCount={2} summary="Mismatch on return type" />);
    expect(screen.getByText(/contradiction warning/i)).toBeInTheDocument();
    expect(screen.getByText(/2 open contradiction\(s\) linked to this page/i)).toBeInTheDocument();
    expect(screen.getByText(/Mismatch on return type/)).toBeInTheDocument();
  });
});
