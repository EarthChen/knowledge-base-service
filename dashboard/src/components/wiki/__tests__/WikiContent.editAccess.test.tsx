import { type ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import WikiContent from "../WikiContent";
import { TestI18nProvider } from "../../../i18n/context";
import type { WikiPageDetail } from "../../../hooks/wikiTypes";

vi.mock("../../../hooks/useWikiAnnotations", () => ({
  useWikiAnnotations: () => ({
    data: [],
    create: { mutate: vi.fn() },
    remove: { mutate: vi.fn(), isPending: false },
  }),
}));

const useAuthMock = vi.fn();
vi.mock("../../../contexts/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));

const baseDetail: WikiPageDetail = {
  path: "/path/to/page.md",
  title: "Page",
  content: "# Hello",
  diagrams: [],
  source_locations: [],
  source_entity_uids: [],
  method_locations: [],
  context: { uid: "wp-uid-1", export_path: "wiki/page.md" },
};

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Provider({ children }: { children: ReactNode }) {
    return (
      <TestI18nProvider>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </TestI18nProvider>
    );
  };
}

describe("WikiContent edit access", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("hides edit controls for non-editors", () => {
    useAuthMock.mockReturnValue({ isEditor: false });
    render(
      <MemoryRouter>
        <WikiContent
          repository="repo"
          businessId="default"
          pagePath={baseDetail.path}
          detail={baseDetail}
          isLoading={false}
          error={null}
        />
      </MemoryRouter>,
      { wrapper: makeWrapper() },
    );
    expect(screen.queryByRole("button", { name: /edit page content/i })).not.toBeInTheDocument();
  });

  it("shows edit controls for editors", () => {
    useAuthMock.mockReturnValue({ isEditor: true });
    render(
      <MemoryRouter>
        <WikiContent
          repository="repo"
          businessId="default"
          pagePath={baseDetail.path}
          detail={baseDetail}
          isLoading={false}
          error={null}
        />
      </MemoryRouter>,
      { wrapper: makeWrapper() },
    );
    expect(screen.getByRole("button", { name: /edit page content/i })).toBeInTheDocument();
  });
});
