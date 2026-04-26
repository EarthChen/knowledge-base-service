import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import WikiVersionBadge from "../WikiVersionBadge";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiVersionBadge", () => {
  it("displays version and date", () => {
    renderWithI18n(<WikiVersionBadge version={3} generatedAt="2026-04-20T10:00:00Z" />);
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it("calls onClick", () => {
    const handler = vi.fn();
    renderWithI18n(<WikiVersionBadge version={1} generatedAt="2026-01-01" onClick={handler} />);
    fireEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalled();
  });

  it("renders a span, not a button, when onClick is omitted", () => {
    renderWithI18n(<WikiVersionBadge version={2} generatedAt="2026-01-01" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/v2/)).toBeInTheDocument();
  });
});
