import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import WikiEditPanel from "../WikiEditPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";

const createSession = vi.fn();
const sendMessage = vi.fn();
const applyEdit = vi.fn();
const discardSession = vi.fn();

vi.mock("../../../hooks/useWikiEditSession", () => ({
  useWikiEditSession: () => ({
    sessionId: null,
    events: [],
    isStreaming: false,
    editedContent: null,
    error: null,
    createSession,
    sendMessage,
    applyEdit,
    discardSession,
  }),
}));

vi.mock("react-diff-viewer-continued", () => ({
  default: () => <div data-testid="diff-viewer" />,
}));

describe("WikiEditPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createSession.mockResolvedValue("sess-1");
  });

  it("renders edit panel with prompt input", () => {
    renderWithI18n(
      <WikiEditPanel pageUid="page-1" currentContent="# Title" businessId="default" />,
    );
    expect(screen.getByPlaceholderText(/describe what you want to change/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^send$/i })).toBeInTheDocument();
  });

  it("submits prompt to create session", async () => {
    const user = userEvent.setup();
    renderWithI18n(
      <WikiEditPanel pageUid="page-1" currentContent="# Title" businessId="default" />,
    );

    await user.type(screen.getByPlaceholderText(/describe what you want to change/i), "Add summary");
    await user.click(screen.getByRole("button", { name: /^send$/i }));

    expect(createSession).toHaveBeenCalledWith("Add summary", "# Title");
  });
});
