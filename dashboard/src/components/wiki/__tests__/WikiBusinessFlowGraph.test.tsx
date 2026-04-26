import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

describe("WikiBusinessFlowGraph", () => {
  it("renders flow container", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ nodes: [], edges: [] }),
      }),
    );
    const WikiBusinessFlowGraph = (await import("../WikiBusinessFlowGraph")).default;
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <WikiBusinessFlowGraph businessId="default" />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("flow-graph-container")).toBeTruthy();
    vi.unstubAllGlobals();
  });
});
