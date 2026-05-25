import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import FocusTrap from "../FocusTrap";

function TrapFixture({ onEscape }: { onEscape?: () => void }) {
  return (
    <FocusTrap onEscape={onEscape}>
      <button type="button">First</button>
      <button type="button">Second</button>
      <button type="button">Last</button>
    </FocusTrap>
  );
}

describe("FocusTrap", () => {
  it("focuses the first focusable element on mount", () => {
    render(<TrapFixture />);
    expect(document.activeElement).toHaveTextContent("First");
  });

  it("wraps Tab from last element to first", async () => {
    const user = userEvent.setup();
    render(<TrapFixture />);
    screen.getByRole("button", { name: "Last" }).focus();
    await user.tab();
    expect(document.activeElement).toHaveTextContent("First");
  });

  it("wraps Shift+Tab from first element to last", async () => {
    const user = userEvent.setup();
    render(<TrapFixture />);
    expect(document.activeElement).toHaveTextContent("First");
    await user.tab({ shift: true });
    expect(document.activeElement).toHaveTextContent("Last");
  });

  it("calls onClose when Escape is pressed", async () => {
    const user = userEvent.setup();
    const onEscape = vi.fn();
    render(<TrapFixture onEscape={onEscape} />);
    await user.keyboard("{Escape}");
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it("restores focus to the previously focused element on unmount", async () => {
    const user = userEvent.setup();

    function ToggleTrap() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button">Outside</button>
          {open ? <TrapFixture onEscape={() => setOpen(false)} /> : null}
          <button
            type="button"
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => setOpen(true)}
          >
            Open trap
          </button>
        </>
      );
    }

    render(<ToggleTrap />);
    const outside = screen.getByRole("button", { name: "Outside" });
    outside.focus();
    expect(document.activeElement).toBe(outside);

    await user.click(screen.getByRole("button", { name: "Open trap" }));
    expect(document.activeElement).toHaveTextContent("First");

    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(outside);
  });
});
