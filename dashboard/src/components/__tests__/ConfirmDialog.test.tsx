import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { ComponentProps } from "react";
import { ConfirmDialog } from "../ConfirmDialog";
import { TestI18nProvider } from "../../i18n/context";

function renderDialog(props?: Partial<ComponentProps<typeof ConfirmDialog>>) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <TestI18nProvider>
      <ConfirmDialog
        title="Delete item"
        message="Are you sure?"
        onConfirm={onConfirm}
        onCancel={onCancel}
        {...props}
      />
    </TestI18nProvider>,
  );
  return { onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  it('renders with role="dialog" and aria-modal', () => {
    renderDialog();
    const dialog = screen.getByRole("dialog", { name: "Delete item" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("Escape calls onCancel", () => {
    const { onCancel } = renderDialog();
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("confirm button calls onConfirm", () => {
    const { onConfirm } = renderDialog({ confirmLabel: "Yes, delete" });
    fireEvent.click(screen.getByRole("button", { name: "Yes, delete" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("renders danger variant styling on confirm button", () => {
    renderDialog({ variant: "danger", confirmLabel: "Delete" });
    const confirm = screen.getByRole("button", { name: "Delete" });
    expect(confirm.className).toMatch(/red/);
  });

  it("generates unique title ids when multiple dialogs mount", () => {
    render(
      <TestI18nProvider>
        <ConfirmDialog title="First" message="One" onConfirm={vi.fn()} onCancel={vi.fn()} />
        <ConfirmDialog title="Second" message="Two" onConfirm={vi.fn()} onCancel={vi.fn()} />
      </TestI18nProvider>,
    );
    const titles = screen.getAllByRole("heading", { level: 3 });
    const ids = titles.map((el) => el.getAttribute("id"));
    expect(ids[0]).toBeTruthy();
    expect(ids[1]).toBeTruthy();
    expect(ids[0]).not.toBe(ids[1]);
    const dialogs = screen.getAllByRole("dialog");
    expect(dialogs[0]).toHaveAttribute("aria-labelledby", ids[0]);
    expect(dialogs[1]).toHaveAttribute("aria-labelledby", ids[1]);
  });
});
