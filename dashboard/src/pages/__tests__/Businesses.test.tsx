import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import Businesses from "../Businesses";
import { renderWithI18n } from "../../test/renderWithI18n";
import { ToastProvider } from "../../components/Toast";
import { AuthProvider } from "../../contexts/AuthContext";
import { BusinessProvider } from "../../contexts/BusinessContext";
import { server } from "../../test/mocks/server";

vi.mock("../../hooks/useBusinessRepositories", () => ({
  useBusinessRepositories: () => ({
    data: { repositories: ["demo"] },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
  useBindRepositories: () => ({
    mutateAsync: vi.fn().mockResolvedValue({}),
    isPending: false,
  }),
}));

function renderBusinesses() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return renderWithI18n(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <BusinessProvider>
          <ToastProvider>
            <MemoryRouter>
              <Businesses />
            </MemoryRouter>
          </ToastProvider>
        </BusinessProvider>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Businesses", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/auth/me", () =>
        HttpResponse.json({ role: "admin", auth_enabled: false, business_id: null }),
      ),
      http.get("/api/v1/businesses", () =>
        HttpResponse.json({
          businesses: [
            { id: "default", name: "Default", description: "Primary", created_at: 1_700_000_000 },
            { id: "team-a", name: "Team Alpha", description: "", created_at: 1_700_000_100 },
          ],
          total: 2,
        }),
      ),
      http.post("/api/v1/businesses", () =>
        HttpResponse.json({ id: "team-b", name: "Team B", description: "", created_at: 1_700_000_200 }),
      ),
    );
  });

  it("renders business list", async () => {
    renderBusinesses();
    expect(screen.getByRole("heading", { name: /businesses/i })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Team Alpha")).toBeInTheDocument();
    });
    expect(screen.getByText("default")).toBeInTheDocument();
  });

  it("shows create button for admin", async () => {
    renderBusinesses();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /new business/i })).toBeInTheDocument();
    });
  });

  it("opens create business form", async () => {
    const user = userEvent.setup();
    renderBusinesses();
    await user.click(await screen.findByRole("button", { name: /new business/i }));
    expect(screen.getByPlaceholderText(/team-alpha/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/team alpha/i)).toBeInTheDocument();
  });

  it("associates create form labels with inputs via htmlFor and id", async () => {
    const user = userEvent.setup();
    renderBusinesses();
    await user.click(await screen.findByRole("button", { name: /new business/i }));

    const idInput = screen.getByLabelText(/business id/i);
    const nameInput = screen.getByLabelText(/^name$/i);
    const descInput = screen.getByLabelText(/^description$/i);

    expect(idInput).toHaveAttribute("id");
    expect(nameInput).toHaveAttribute("id");
    expect(descInput).toHaveAttribute("id");

    expect(screen.getByText(/business id/i)).toHaveAttribute("for", idInput.id);
    expect(screen.getByText(/^name$/i)).toHaveAttribute("for", nameInput.id);
    expect(screen.getByText(/^description$/i)).toHaveAttribute("for", descInput.id);
  });

  it("creates a business from the form", async () => {
    const user = userEvent.setup();
    renderBusinesses();
    await user.click(await screen.findByRole("button", { name: /new business/i }));
    await user.type(screen.getByPlaceholderText(/team-alpha/i), "team-b");
    await user.type(screen.getByPlaceholderText(/team alpha/i), "Team B");
    const createButtons = screen.getAllByRole("button", { name: /new business/i });
    await user.click(createButtons[createButtons.length - 1]!);
    await waitFor(() => expect(screen.queryByPlaceholderText(/team-alpha/i)).not.toBeInTheDocument());
  });

  it("expands repository binding panel for non-default business", async () => {
    const user = userEvent.setup();
    renderBusinesses();
    await user.click(await screen.findByRole("button", { name: /manage repositories/i }));
    expect(screen.getByPlaceholderText(/repository-id/i)).toBeInTheDocument();
  });

  it("switches current business", async () => {
    const user = userEvent.setup();
    renderBusinesses();
    await user.click(await screen.findByRole("button", { name: /^switch$/i }));
    await waitFor(() => expect(screen.getAllByText(/current/i).length).toBeGreaterThan(0));
  });

  it("opens confirm dialog on delete and deletes on confirm", async () => {
    const user = userEvent.setup();
    let deletedId: string | undefined;
    server.use(
      http.delete("/api/v1/businesses/:id", ({ params }) => {
        deletedId = params.id as string;
        return HttpResponse.json({ deleted: params.id });
      }),
    );
    renderBusinesses();
    await waitFor(() => expect(screen.getByText("Team Alpha")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));
    await waitFor(() => expect(deletedId).toBe("team-a"));
  });
});
