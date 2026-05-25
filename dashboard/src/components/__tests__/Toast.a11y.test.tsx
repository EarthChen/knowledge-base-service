import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ToastProvider, useToast } from "../Toast";

function ShowToastTrigger({ type = "info" as const, msg = "hello" }) {
  const { toast } = useToast();
  return (
    <button type="button" onClick={() => toast(type, msg)}>
      show toast
    </button>
  );
}

describe("Toast dismiss control a11y", () => {
  it('uses type="button" and aria-label on dismiss', () => {
    render(
      <ToastProvider>
        <ShowToastTrigger />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "show toast" }));
    const dismiss = screen.getByRole("button", { name: "Dismiss notification" });
    expect(dismiss).toHaveAttribute("type", "button");
    expect(dismiss).toHaveAttribute("aria-label", "Dismiss notification");
  });

  it("toast container has aria-live region", () => {
    render(
      <ToastProvider>
        <ShowToastTrigger />
      </ToastProvider>,
    );
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveAttribute("aria-atomic", "true");
  });

  it("error toast uses role=alert with assertive", () => {
    render(
      <ToastProvider>
        <ShowToastTrigger type="error" msg="something failed" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "show toast" }));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveAttribute("aria-live", "assertive");
  });

  it("success/info toast uses role=status", () => {
    render(
      <ToastProvider>
        <ShowToastTrigger type="success" msg="saved" />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "show toast" }));
    const items = screen.getAllByRole("status");
    // Container + toast item both have role="status"
    expect(items.length).toBeGreaterThanOrEqual(2);
  });

  it("decorative icons are hidden from screen readers", () => {
    render(
      <ToastProvider>
        <ShowToastTrigger />
      </ToastProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "show toast" }));
    // The SVG icons should have aria-hidden
    const svgs = document.querySelectorAll("svg[aria-hidden='true']");
    expect(svgs.length).toBeGreaterThanOrEqual(1);
  });
});
