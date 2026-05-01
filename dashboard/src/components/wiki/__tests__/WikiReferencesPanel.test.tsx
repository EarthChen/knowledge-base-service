import type { ComponentProps } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import WikiReferencesPanel from "../WikiReferencesPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { useWikiReferences } from "../../../hooks/useWikiReferences";
import en from "../../../i18n/en";

vi.mock("../../../hooks/useWikiReferences", () => ({
  useWikiReferences: vi.fn(),
}));

describe("WikiReferencesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderPanel(
    overrides: Partial<ComponentProps<typeof WikiReferencesPanel>> = {},
  ) {
    return renderWithI18n(
      <MemoryRouter>
        <WikiReferencesPanel
          businessId="b1"
          pageUid="uid-1"
          pagePath=""
          repository="owner/repo"
          isOpen={true}
          onToggle={vi.fn()}
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("renders loading spinner when fetching references", () => {
    vi.mocked(useWikiReferences).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as ReturnType<typeof useWikiReferences>);

    renderPanel();
    expect(document.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("shows empty state when references list is empty", () => {
    vi.mocked(useWikiReferences).mockReturnValue({
      data: { page_uid: "uid-1", outgoing: [], incoming: [] },
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useWikiReferences>);

    renderPanel();
    expect(screen.getByText(en.wiki.referencesEmpty)).toBeInTheDocument();
  });

  it("lists outgoing references with titles", () => {
    vi.mocked(useWikiReferences).mockReturnValue({
      data: {
        page_uid: "uid-1",
        outgoing: [
          {
            relation_type: "calls",
            title: "Callee Page",
            path: "/callee.md",
            repository: "owner/repo",
            context: "ctx",
          },
        ],
        incoming: [],
      },
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useWikiReferences>);

    renderPanel();
    expect(screen.getByRole("button", { name: /Callee Page/ })).toBeInTheDocument();
    expect(screen.getByText(/Outgoing \(1\)/)).toBeInTheDocument();
  });
});
