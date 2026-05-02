import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import AskPanel from "../AskPanel";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { ToastProvider } from "../../Toast";

const askFn = vi.hoisted(() => vi.fn());
const streamingRef = vi.hoisted(() => ({ current: false }));
const useWikiAskMock = vi.hoisted(() => vi.fn());

vi.mock("../../../hooks/useWikiAsk", () => ({
  useWikiAsk: (...args: unknown[]) => useWikiAskMock(...args),
}));

vi.mock("../../../hooks/useConversationHistory", () => ({
  useConversationHistory: () => ({
    list: vi.fn(() => []),
    get: vi.fn(),
    save: vi.fn(),
    clear: vi.fn(),
  }),
}));

vi.mock("../MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <div data-testid="md">{content}</div>,
}));

vi.mock("../ReasoningPathPanel", () => ({
  ReasoningPathPanel: () => null,
}));

function renderAsk(repository: string | undefined, pageContext?: string) {
  return renderWithI18n(
    <MemoryRouter>
      <ToastProvider>
        <AskPanel repository={repository} pageContext={pageContext} />
      </ToastProvider>
    </MemoryRouter>,
  );
}

describe("AskPanel", () => {
  beforeEach(() => {
    streamingRef.current = false;
    askFn.mockReset();
    useWikiAskMock.mockReset();
    useWikiAskMock.mockImplementation(() => ({
      answer: "",
      sources: [],
      ragStages: [],
      get isStreaming() {
        return streamingRef.current;
      },
      error: null,
      reasoningPath: null,
      ask: askFn,
      cancel: vi.fn(),
      reset: vi.fn(),
      setAnswer: vi.fn(),
      setSources: vi.fn(),
      conversationId: undefined as string | undefined,
    }));
  });

  it("renders nothing when repository is missing", () => {
    const { container } = renderAsk(undefined);
    expect(container.querySelector("#wiki-ask-panel")).toBeNull();
  });

  it("renders nothing when repository is whitespace-only", () => {
    const { container } = renderAsk("   ");
    expect(container.querySelector("#wiki-ask-panel")).toBeNull();
  });

  it("renders panel with minimal repository prop", () => {
    renderAsk("my-repo");
    expect(screen.getByText("Ask wiki")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask a question about this repository/i)).toBeInTheDocument();
  });

  it("textarea accepts text", async () => {
    const user = userEvent.setup();
    renderAsk("my-repo");
    const textarea = screen.getByPlaceholderText(/Ask a question about this repository/i);
    await user.type(textarea, "explain auth");
    expect(textarea).toHaveValue("explain auth");
  });

  it("submitting the form invokes ask when not streaming", async () => {
    const user = userEvent.setup();
    renderAsk("my-repo");
    const textarea = screen.getByPlaceholderText(/Ask a question about this repository/i);
    await user.type(textarea, "what is OAuth?");
    fireEvent.submit(textarea.closest("form")!);
    expect(askFn).toHaveBeenCalledWith({ question: "what is OAuth?" });
  });

  it("passes repository and pageContext into useWikiAsk", () => {
    renderAsk("repo-x", "[Current page: Home]\nsummary");
    expect(useWikiAskMock).toHaveBeenCalledWith("repo-x", "[Current page: Home]\nsummary");
  });

  it("shows streaming loading affordance while isStreaming and answer is empty", () => {
    streamingRef.current = true;
    renderAsk("my-repo");
    expect(screen.getByRole("status")).toHaveTextContent("Retrieving context and generating");
  });

  it("shows error message when useWikiAsk returns an error", () => {
    useWikiAskMock.mockImplementation(() => ({
      answer: "",
      sources: [],
      ragStages: [],
      get isStreaming() {
        return false;
      },
      error: "Something went wrong",
      reasoningPath: null,
      ask: askFn,
      cancel: vi.fn(),
      reset: vi.fn(),
      setAnswer: vi.fn(),
      setSources: vi.fn(),
      conversationId: undefined as string | undefined,
    }));
    renderAsk("my-repo");
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });
});
