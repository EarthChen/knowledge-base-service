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
    expect(screen.getByText(/Retrieving context and generating/)).toBeInTheDocument();
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

  it("renders answer and sources when available", () => {
    useWikiAskMock.mockImplementation(() => ({
      answer: "OAuth uses tokens for authorization.",
      sources: [{ entity: "AuthService", file_path: "auth.py", start_line: 1, wiki_page: "/auth", relevance_score: 0.9 }],
      ragStages: [],
      get isStreaming() {
        return false;
      },
      error: null,
      reasoningPath: null,
      ask: askFn,
      cancel: vi.fn(),
      reset: vi.fn(),
      setAnswer: vi.fn(),
      setSources: vi.fn(),
      conversationId: "conv-1",
    }));
    renderAsk("my-repo");
    expect(screen.getByText(/OAuth uses tokens/)).toBeInTheDocument();
    expect(screen.getByText("AuthService")).toBeInTheDocument();
  });

  it("shows cancel button while streaming", async () => {
    const cancelFn = vi.fn();
    streamingRef.current = true;
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
      cancel: cancelFn,
      reset: vi.fn(),
      setAnswer: vi.fn(),
      setSources: vi.fn(),
      conversationId: undefined as string | undefined,
    }));
    const user = userEvent.setup();
    renderAsk("my-repo");
    await user.click(screen.getByRole("button", { name: /stop/i }));
    expect(cancelFn).toHaveBeenCalled();
  });

  it("exposes collapse toggle aria-expanded and accessible form controls", () => {
    renderAsk("my-repo");
    const toggle = screen.getByRole("button", { name: /ask wiki/i });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const textarea = screen.getByRole("textbox", { name: /ask a question about this repository/i });
    expect(textarea).toHaveAttribute("aria-label");
    expect(screen.getByRole("button", { name: /submit question/i })).toBeInTheDocument();
  });

  it("exposes conversation history toggle aria-expanded", async () => {
    const user = userEvent.setup();
    renderAsk("my-repo");
    const historyToggle = screen.getByRole("button", { name: /^history$/i });
    expect(historyToggle).toHaveAttribute("aria-expanded", "false");
    await user.click(historyToggle);
    expect(historyToggle).toHaveAttribute("aria-expanded", "true");
  });

  it("renders plain text while streaming instead of MarkdownRenderer", () => {
    streamingRef.current = true;
    useWikiAskMock.mockImplementation(() => ({
      answer: "**partial** answer",
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
    renderAsk("my-repo");
    expect(screen.queryByTestId("md")).not.toBeInTheDocument();
    expect(screen.getByText("**partial** answer")).toBeInTheDocument();
  });

  it("uses MarkdownRenderer after streaming completes", () => {
    useWikiAskMock.mockImplementation(() => ({
      answer: "**done** answer",
      sources: [],
      ragStages: [],
      get isStreaming() {
        return false;
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
    renderAsk("my-repo");
    expect(screen.getByTestId("md")).toHaveTextContent("**done** answer");
  });
});
