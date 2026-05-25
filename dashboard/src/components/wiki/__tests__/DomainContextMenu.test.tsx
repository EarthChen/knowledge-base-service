import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import DomainContextMenu from "../DomainContextMenu";
import { TestI18nProvider } from "../../../i18n/context";

const defaultProps = {
  x: 100,
  y: 200,
  nodeUid: "uid-1",
  nodeTitle: "Payment",
  isRoot: false,
  onClose: vi.fn(),
  onRename: vi.fn(),
  onDelete: vi.fn(),
  onCreateSubdomain: vi.fn(),
  onMove: vi.fn(),
  onMerge: vi.fn(),
};

function renderMenu(overrides: Partial<typeof defaultProps> = {}) {
  const props = { ...defaultProps, ...overrides, onClose: overrides.onClose ?? vi.fn() };
  return render(
    <TestI18nProvider>
      <DomainContextMenu {...props} />
    </TestI18nProvider>,
  );
}

describe("DomainContextMenu keyboard navigation", () => {
  it("focuses the first menuitem on mount", () => {
    renderMenu();
    const items = screen.getAllByRole("menuitem");
    expect(document.activeElement).toBe(items[0]);
  });

  it("ArrowDown moves focus to the next menuitem", () => {
    renderMenu();
    const menu = screen.getByRole("menu");
    const items = screen.getAllByRole("menuitem");
    items[0]!.focus();
    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(document.activeElement).toBe(items[1]);
  });

  it("ArrowUp moves focus to the previous menuitem", () => {
    renderMenu();
    const menu = screen.getByRole("menu");
    const items = screen.getAllByRole("menuitem");
    items[1]!.focus();
    fireEvent.keyDown(menu, { key: "ArrowUp" });
    expect(document.activeElement).toBe(items[0]);
  });

  it("Home focuses the first enabled menuitem", () => {
    renderMenu();
    const menu = screen.getByRole("menu");
    const items = screen.getAllByRole("menuitem");
    items[2]!.focus();
    fireEvent.keyDown(menu, { key: "Home" });
    expect(document.activeElement).toBe(items[0]);
  });

  it("End focuses the last enabled menuitem", () => {
    renderMenu();
    const menu = screen.getByRole("menu");
    const items = screen.getAllByRole("menuitem");
    items[0]!.focus();
    fireEvent.keyDown(menu, { key: "End" });
    expect(document.activeElement).toBe(items[items.length - 1]);
  });

  it("Escape closes the menu", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderMenu({ onClose });
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});
