import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import WikiLandingPage from "../WikiLandingPage";
import { renderWithI18n } from "../../../test/renderWithI18n";

vi.mock("../WikiCoverageCard", () => ({
  default: () => <div data-testid="wiki-coverage-mock">coverage card</div>,
}));

vi.mock("../../../hooks/useWikiTree", () => ({
  useWikiTree: () => ({
    data: { tree: [] },
    isLoading: false,
    isError: false,
    error: null,
  }),
}));

describe("WikiLandingPage", () => {
  it("renders coverage card and empty state when wiki tree has no roots", () => {
    renderWithI18n(
      <MemoryRouter>
        <WikiLandingPage businessId="b1" viewType="business_domain" wikiTier={null} />
      </MemoryRouter>,
    );

    expect(screen.getByTestId("wiki-coverage-mock")).toBeInTheDocument();
    expect(screen.getByText("No wiki pages found.")).toBeVisible();
  });

  it("exposes a landmarks-friendly heading above the domains list (accessibility)", () => {
    renderWithI18n(
      <MemoryRouter>
        <WikiLandingPage businessId="b1" viewType="business_domain" wikiTier={null} />
      </MemoryRouter>,
    );

    const heading = screen.getByRole("heading", { level: 3, name: /business domains/i });
    expect(heading).toBeVisible();
    const empty = screen.getByText("No wiki pages found.");
    expect(heading.compareDocumentPosition(empty)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });
});
