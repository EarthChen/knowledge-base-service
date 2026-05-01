import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiLintPanel from "../WikiLintPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { wikiLint } from "../../../api/client";
import en from "../../../i18n/en";
import type { WikiLintReport } from "../../../api/types";

vi.mock("../../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../../api/client")>();
  return { ...mod, wikiLint: vi.fn() };
});

function renderLint() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false }, gcTime: 0 },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <WikiLintPanel repository="org/repo-wiki" />
    </QueryClientProvider>,
  );
}

describe("WikiLintPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows empty hint until a lint run completes", () => {
    renderLint();
    expect(screen.getByText(en.wiki.lintEmptyHint)).toBeInTheDocument();
    expect(screen.getByText(en.wiki.lintHelp)).toBeInTheDocument();
  });

  it("renders lint statistics and issues after run succeeds", async () => {
    const user = userEvent.setup();
    const report: WikiLintReport = {
      issues: [
        {
          severity: "error",
          category: "broken_links",
          message: "Link to nowhere",
          page_path: "/broken.md",
        },
      ],
      stats: { total: 1, errors: 1, warnings: 0, info: 0 },
      checked_at: "2026-05-01T12:00:00.000Z",
      scope: "all",
    };
    vi.mocked(wikiLint).mockResolvedValue(report);

    renderLint();
    await user.click(screen.getByRole("button", { name: en.wiki.lintRunCheck }));

    await waitFor(() => expect(screen.getByText("Link to nowhere")).toBeInTheDocument());
    expect(screen.getByText(new RegExp(`${en.wiki.lintTotal}\\s+1`, "u"))).toBeInTheDocument();
    expect(wikiLint).toHaveBeenCalledWith("org/repo-wiki", "all");
  });

  it("shows no-issues empty state when report has zero issues", async () => {
    const user = userEvent.setup();
    const report: WikiLintReport = {
      issues: [],
      stats: { total: 0, errors: 0, warnings: 0, info: 0 },
      checked_at: "2026-05-01T12:00:00.000Z",
      scope: "all",
    };
    vi.mocked(wikiLint).mockResolvedValue(report);

    renderLint();
    await user.click(screen.getByRole("button", { name: en.wiki.lintRunCheck }));
    await waitFor(() => expect(screen.getByText(en.wiki.lintNoIssues)).toBeInTheDocument());
  });
});
