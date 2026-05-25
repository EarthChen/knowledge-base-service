import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GraphContextCards from "../GraphContextCards";
import { renderWithI18n } from "../../test/renderWithI18n";
import { ToastProvider } from "../Toast";

const sampleItems = [
  {
    name: "caller",
    source: "callee",
    relationship: "calls",
    file: "src/a.ts",
    line: 10,
  },
  {
    name: "doWork",
    source: "Worker",
    relationship: "method_of",
    file: "src/worker.ts",
    line: 20,
  },
  {
    name: "Child",
    source: "Parent",
    relationship: "subclass_of",
    file: "src/child.ts",
    line: 5,
  },
  {
    type: "business_flow",
    related_function: "runFlow",
    data: { bf: { properties: { name: "Checkout" } }, f: { properties: { name: "pay" } } },
  },
  { unexpected: true },
];

describe("GraphContextCards", () => {
  it("renders grouped graph context sections", () => {
    renderWithI18n(
      <ToastProvider>
        <GraphContextCards items={sampleItems} />
      </ToastProvider>,
    );

    expect(screen.getByText(/call chain/i)).toBeInTheDocument();
    expect(screen.getByText(/methods/i)).toBeInTheDocument();
    expect(screen.getByText(/inheritance/i)).toBeInTheDocument();
    expect(screen.getByText(/business flows/i)).toBeInTheDocument();
    expect(screen.getByText("caller")).toBeInTheDocument();
    expect(screen.getByText("Checkout")).toBeInTheDocument();
  });

  it("toggles collapsible sections", async () => {
    const user = userEvent.setup();
    renderWithI18n(
      <ToastProvider>
        <GraphContextCards items={sampleItems} />
      </ToastProvider>,
    );

    const callChainToggle = screen.getByRole("button", { name: /call chain/i });
    await user.click(callChainToggle);
    expect(screen.queryByText("caller")).not.toBeInTheDocument();
    await user.click(callChainToggle);
    expect(screen.getByText("caller")).toBeInTheDocument();
  });
});
