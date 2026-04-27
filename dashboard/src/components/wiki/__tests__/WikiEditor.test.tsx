import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TestI18nProvider } from "../../../i18n/context";

describe("WikiEditor", () => {
  it("renders save and cancel buttons", async () => {
    const { WikiEditor } = await import("../WikiEditor");
    const qc = new QueryClient();
    render(
      <TestI18nProvider>
        <QueryClientProvider client={qc}>
          <WikiEditor
            pageUid="test-uid"
            initialContent="# Test"
            currentVersion={1}
            onClose={() => {}}
          />
        </QueryClientProvider>
      </TestI18nProvider>,
    );
    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
  });
});
