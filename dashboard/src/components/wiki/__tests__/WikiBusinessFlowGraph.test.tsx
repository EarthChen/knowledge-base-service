import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderWithI18n } from "../../../test/renderWithI18n";
import { api } from "../../../api/client";

vi.mock("../../../api/client", () => ({ api: vi.fn() }));

describe("WikiBusinessFlowGraph", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders flow container", async () => {
    vi.mocked(api).mockResolvedValue({ nodes: [], edges: [] });
    const WikiBusinessFlowGraph = (await import("../WikiBusinessFlowGraph")).default;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <WikiBusinessFlowGraph businessId="default" />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("flow-graph-container")).toBeTruthy();
  });

  it("shows error when flows request fails", async () => {
    vi.mocked(api).mockRejectedValue(new Error("upstream failed"));
    const WikiBusinessFlowGraph = (await import("../WikiBusinessFlowGraph")).default;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderWithI18n(
      <QueryClientProvider client={qc}>
        <WikiBusinessFlowGraph businessId="default" />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText("Failed to load flows: upstream failed"),
    ).toBeInTheDocument();
  });
});
