import { type ReactNode } from "react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
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

function ExplorerLocationEcho() {
  const { pathname, search } = useLocation();
  return <div data-testid="dest">{`${pathname}${search}`}</div>;
}

const baseDetail: WikiPageDetail = {
  path: "/path/to/page.md",
  title: "Page",
  content: "# Hello",
  diagrams: [],
  source_locations: [],
  source_entity_uids: ["Function:repo:com.example.Foo"],
  method_locations: [],
  context: { uid: "wp-uid-1" },
};

const contentProps = {
  repository: "repo",
  businessId: "default",
  pagePath: baseDetail.path,
  detail: baseDetail,
  isLoading: false,
  error: null,
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

describe("WikiContent — graph link", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders View in Graph when source entities are available", () => {
    render(
      <MemoryRouter initialEntries={["/w"]}>
        <Routes>
          <Route path="/w" element={<WikiContent {...contentProps} />} />
          <Route path="/explorer" element={<ExplorerLocationEcho />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: makeWrapper() },
    );
    expect(screen.getByRole("button", { name: /view in graph/i })).toBeInTheDocument();
  });

  it("navigates to /explorer?node=… with encoded uid", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/w"]}>
        <Routes>
          <Route path="/w" element={<WikiContent {...contentProps} />} />
          <Route path="/explorer" element={<ExplorerLocationEcho />} />
        </Routes>
      </MemoryRouter>,
      { wrapper: makeWrapper() },
    );
    await user.click(screen.getByRole("button", { name: /view in graph/i }));
    expect(await screen.findByTestId("dest")).toHaveTextContent(
      `/explorer?node=${encodeURIComponent("Function:repo:com.example.Foo")}`,
    );
  });
});
