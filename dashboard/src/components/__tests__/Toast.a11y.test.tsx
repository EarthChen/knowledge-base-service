import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ToastProvider, useToast } from "../Toast";

function ShowToastTrigger() {
  const { toast } = useToast();
  return (
    <button type="button" onClick={() => toast("info", "hello")}>
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
});
