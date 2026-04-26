import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiVersionBadge from "../WikiVersionBadge";

describe("WikiVersionBadge", () => {
  it("displays version and date", () => {
    render(<WikiVersionBadge version={3} generatedAt="2026-04-20T10:00:00Z" />);
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("calls onClick", () => {
    const handler = vi.fn();
    render(<WikiVersionBadge version={1} generatedAt="2026-01-01" onClick={handler} />);
    fireEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalled();
  });
});
