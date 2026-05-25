import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Documents from "../Documents";
import { renderWithI18n } from "../../test/renderWithI18n";

vi.mock("../../components/wiki/MarkdownRenderer", () => ({
  default: ({ content }: { content: string }) => <div data-testid="markdown">{content}</div>,
}));

vi.mock("../../api/hooks", () => ({
  useRepositories: () => ({
    data: { repositories: [{ repository: "demo", nodes: 5, git_url: "" }] },
  }),
  useDocuments: () => ({
    data: {
      documents: [
        {
          uid: "doc-1",
          title: "README",
          file: "README.md",
          repository: "demo",
        },
        {
          uid: "doc-2",
          title: "Guide",
          file: "docs/guide.md",
          repository: "demo",
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
  useDocument: () => ({
    data: {
      uid: "doc-1",
      title: "README",
      file: "README.md",
      content: "# Hello",
      sections: [{ uid: "sec-1", title: "Intro", level: 1, content: "# Hello" }],
    },
    isLoading: false,
    error: null,
  }),
}));

function renderDocuments() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Documents />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Documents", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders document browser title and search input", () => {
    renderDocuments();
    expect(screen.getByRole("heading", { name: /document browser/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/search code/i)).toBeInTheDocument();
  });

  it("renders repository selector and document tree", () => {
    renderDocuments();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(screen.getAllByText("README").length).toBeGreaterThan(0);
  });

  it("filters documents via search input in tree", async () => {
    const user = userEvent.setup();
    renderDocuments();
    const search = screen.getByPlaceholderText(/search code/i);
    await user.type(search, "nomatch");
    expect(screen.queryByRole("button", { name: "README" })).not.toBeInTheDocument();
  });

  it("shows document content when selecting a tree item", async () => {
    const user = userEvent.setup();
    renderDocuments();
    await user.click(screen.getAllByRole("button", { name: "README" })[0]!);
    expect(screen.getByTestId("markdown")).toHaveTextContent("# Hello");
  });

  it("folder toggle buttons expose aria-expanded", async () => {
    const user = userEvent.setup();
    renderDocuments();
    const folderToggle = screen.getByRole("button", { name: "docs" });
    expect(folderToggle).toHaveAttribute("aria-expanded", "false");
    await user.click(folderToggle);
    expect(folderToggle).toHaveAttribute("aria-expanded", "true");
  });

  it("search clear button has accessible name", async () => {
    const user = userEvent.setup();
    renderDocuments();
    const search = screen.getByPlaceholderText(/search code/i);
    await user.type(search, "test");
    expect(screen.getByRole("button", { name: /clear search/i })).toBeInTheDocument();
  });
});
