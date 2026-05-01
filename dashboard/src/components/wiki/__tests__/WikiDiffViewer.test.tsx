import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import WikiDiffViewer from "../WikiDiffViewer";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { useWikiDiff } from "../../../hooks/useWikiDiff";
import en from "../../../i18n/en";

vi.mock("../../../hooks/useWikiDiff", () => ({
  useWikiDiff: vi.fn(),
}));

vi.mock("react-diff-viewer-continued", () => ({
  default: ({ oldValue, newValue }: { oldValue: string; newValue: string }) => (
    <div data-testid="stub-diff">{oldValue}|||{newValue}</div>
  ),
}));

describe("WikiDiffViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  function renderViewer() {
    return renderWithI18n(
      <WikiDiffViewer businessId="b1" pageUid="p1" fromVersion={1} toVersion={2} />,
    );
  }

  it("shows loading spinner while diff loads", () => {
    vi.mocked(useWikiDiff).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as ReturnType<typeof useWikiDiff>);

    renderViewer();
    expect(document.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("shows error message when request fails", () => {
    vi.mocked(useWikiDiff).mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
    } as ReturnType<typeof useWikiDiff>);

    renderViewer();
    expect(screen.getByText(en.wiki.diffLoadError)).toBeInTheDocument();
  });

  it("renders diff viewer with reconstructed sides from hunks", () => {
    vi.mocked(useWikiDiff).mockReturnValue({
      data: {
        from_version: 1,
        to_version: 2,
        hunks: [{ old_start: 1, old_lines: 1, new_start: 1, new_lines: 1, content: "-old line\n+new line\n" }],
      },
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useWikiDiff>);

    renderViewer();
    expect(screen.getByTestId("stub-diff")).toHaveTextContent("old line|||new line");
  });

  it("renders empty strings when hunks are empty", () => {
    vi.mocked(useWikiDiff).mockReturnValue({
      data: { from_version: 1, to_version: 2, hunks: [] },
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useWikiDiff>);

    renderViewer();
    expect(screen.getByTestId("stub-diff")).toHaveTextContent("|||");
  });

  it("invokes onClose when close control is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    vi.mocked(useWikiDiff).mockReturnValue({
      data: { from_version: 1, to_version: 2, hunks: [] },
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useWikiDiff>);

    renderWithI18n(
      <WikiDiffViewer businessId="b1" pageUid="p1" fromVersion={1} toVersion={2} onClose={onClose} />,
    );
    await user.click(screen.getByRole("button", { name: en.wiki.diffClose }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
