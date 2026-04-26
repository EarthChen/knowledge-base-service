import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import WikiStaleAlert from "../WikiStaleAlert";
import { renderWithI18n } from "../../../test/renderWithI18n";
import en from "../../../i18n/en";

const STALE_MSG = en.wiki.staleWarning.replace("{date}", "2026-01-01");

describe("WikiStaleAlert", () => {
  it("renders nothing when not stale", () => {
    const { container } = renderWithI18n(
      <WikiStaleAlert generatedAtLabel="2026-01-01" isStale={false} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders staleWarning i18n when stale", () => {
    renderWithI18n(<WikiStaleAlert generatedAtLabel="2026-01-01" isStale />);
    expect(screen.getByText(STALE_MSG)).toBeInTheDocument();
  });
});
