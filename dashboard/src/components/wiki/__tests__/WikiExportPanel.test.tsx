import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import WikiExportPanel from "../WikiExportPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { wikiExportExecute, wikiExportPreview } from "../../../api/client";
import en from "../../../i18n/en";
import type { WikiExportResult } from "../../../api/types";

const previewMock = vi.fn();
const executeMock = vi.fn();

vi.mock("../../../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../../../api/client")>();
  return {
    ...mod,
    wikiExportPreview: (...a: Parameters<typeof mod.wikiExportPreview>) => previewMock(...a),
    wikiExportExecute: (...a: Parameters<typeof mod.wikiExportExecute>) => executeMock(...a),
  };
});

function renderExport() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false }, gcTime: 0 },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <WikiExportPanel repository="org/repo-wiki" />
    </QueryClientProvider>,
  );
}

describe("WikiExportPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    previewMock.mockResolvedValue({
      diffs: [
        {
          file_path: "a.md",
          action: "create",
          wiki_content: "",
          repo_content: null,
          diff_summary: "will create",
        },
      ],
      total_files: 1,
      created: 1,
      updated: 0,
      skipped: 0,
    } satisfies WikiExportResult);
    executeMock.mockResolvedValue({
      diffs: [],
      total_files: 1,
      created: 1,
      updated: 0,
      skipped: 0,
    } satisfies WikiExportResult);
  });

  it("renders export options and disables preview until directory filled", async () => {
    const user = userEvent.setup();
    renderExport();
    expect(screen.getByText(en.wiki.exportTitle)).toBeInTheDocument();
    expect(screen.getByText(en.wiki.exportHelp)).toBeInTheDocument();
    const previewBtn = screen.getByRole("button", { name: en.wiki.exportPreviewButton });
    expect(previewBtn).toBeDisabled();
    await user.type(screen.getByPlaceholderText(en.wiki.exportTargetPlaceholder), "/tmp/out");
    expect(previewBtn).not.toBeDisabled();
  });

  it("runs preview then export selected invokes execute with chosen files", async () => {
    const user = userEvent.setup();
    renderExport();

    await user.type(screen.getByPlaceholderText(en.wiki.exportTargetPlaceholder), "/data/wiki");
    await user.click(screen.getByRole("button", { name: en.wiki.exportPreviewButton }));

    await waitFor(() =>
      expect(previewMock).toHaveBeenCalledWith("org/repo-wiki", "/data/wiki"),
    );

    await waitFor(() => expect(screen.getByRole("button", { name: en.wiki.exportSelected })).toBeInTheDocument());

    await user.click(screen.getByRole("button", { name: en.wiki.exportSelected }));

    await waitFor(() =>
      expect(executeMock).toHaveBeenCalledWith("org/repo-wiki", "/data/wiki", ["a.md"]),
    );
  });
});
