import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Repositories from "../Repositories";
import { renderWithI18n } from "../../test/renderWithI18n";
import { ToastProvider } from "../../components/Toast";

vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "default",
    setCurrentBusiness: vi.fn(),
    businesses: [{ id: "default", name: "Default", description: "", created_at: 0 }],
    isLoading: false,
    isBound: false,
  }),
}));

vi.mock("../../contexts/AuthContext", () => ({
  useAuth: () => ({ isAdmin: true, isLoading: false }),
}));

vi.mock("../../hooks/useBusinessRepositories", () => ({
  useBusinessRepositories: () => ({
    data: { repositories: ["demo-repo"] },
    isLoading: false,
    isFetched: true,
  }),
}));

const mutateAsync = vi.fn().mockResolvedValue({ deleted_nodes: 42 });
const refetch = vi.fn();

vi.mock("../../api/hooks", () => ({
  useRepositories: () => ({
    data: {
      repositories: [{ repository: "demo-repo", nodes: 128, git_url: "https://git.example.com/demo.git" }],
    },
    isLoading: false,
    error: null,
    refetch,
  }),
  useDeleteRepository: () => ({
    mutateAsync,
    isPending: false,
  }),
}));

function renderRepositories() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemoryRouter>
          <Repositories />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("Repositories", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders repositories title and table headers", () => {
    renderRepositories();
    expect(screen.getByRole("heading", { name: /repositories/i })).toBeInTheDocument();
    expect(screen.getByText(/repository/i)).toBeInTheDocument();
    expect(screen.getByText(/nodes/i)).toBeInTheDocument();
    expect(screen.getByText(/actions/i)).toBeInTheDocument();
  });

  it("renders repo list for current business", () => {
    renderRepositories();
    expect(screen.getByText("demo-repo")).toBeInTheDocument();
    expect(screen.getByText("128")).toBeInTheDocument();
  });

  it("opens confirm dialog on delete and deletes on confirm", async () => {
    const user = userEvent.setup();
    renderRepositories();
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText(/demo-repo/i)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("demo-repo"));
    expect(refetch).toHaveBeenCalled();
  });

  it("uses i18n keys for sync button label and title", () => {
    renderRepositories();
    const syncBtn = screen.getByRole("button", { name: /sync & wiki/i });
    expect(syncBtn).toHaveAttribute("title", "Update code & regenerate wiki");
    expect(syncBtn.textContent).toMatch(/sync & wiki/i);
  });
});
