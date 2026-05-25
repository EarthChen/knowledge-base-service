import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DeepSearchSection from "../DeepSearchSection";
import { renderWithI18n } from "../../test/renderWithI18n";

const start = vi.fn();
const mutate = vi.fn();

vi.mock("../../api/hooks", () => ({
  useDeepSearch: () => ({
    mutate,
    isPending: false,
    error: null,
    data: {
      search_trace: [{ step: "query", query: "auth" }],
      analysis: "",
      business_flows: [],
      code_locations: [],
    },
  }),
}));

vi.mock("../../hooks/useDeepSearchStream", () => ({
  useDeepSearchStream: () => ({
    start,
    cancel: vi.fn(),
    isStreaming: false,
    events: [],
    stages: [],
    result: null,
    error: null,
    conclusion: null,
  }),
}));

vi.mock("../wiki/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <div>{content}</div>,
}));

function renderDeepSearch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <DeepSearchSection />
    </QueryClientProvider>,
  );
}

describe("DeepSearchSection", () => {
  it("renders deep search form", () => {
    renderDeepSearch();
    expect(screen.getByRole("heading", { name: /deep search \(llm\)/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask a complex question/i)).toBeInTheDocument();
  });

  it("submits streaming search", async () => {
    const user = userEvent.setup();
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    renderWithI18n(
      <QueryClientProvider client={client}>
        <DeepSearchSection showTitle={false} />
      </QueryClientProvider>,
    );
    await user.type(screen.getByPlaceholderText(/ask a complex question/i), "auth flow");
    await user.click(screen.getByRole("button", { name: /^search$/i }));
    expect(start).toHaveBeenCalledWith({ query: "auth flow", max_iterations: 3 });
  });

  it("exposes search trace toggle aria-expanded", async () => {
    const user = userEvent.setup();
    renderDeepSearch();
    await user.click(screen.getByRole("checkbox", { name: /live progress/i }));

    const traceToggle = screen.getByRole("button", { name: /search trace/i });
    expect(traceToggle).toHaveAttribute("aria-expanded", "true");
    await user.click(traceToggle);
    expect(traceToggle).toHaveAttribute("aria-expanded", "false");
  });
});
