import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import WikiUpdateNotification from "../WikiUpdateNotification";
import { renderWithI18n } from "../../../test/renderWithI18n";

describe("WikiUpdateNotification", () => {
  it("shows page name", () => {
    renderWithI18n(
      <WikiUpdateNotification pagePath="user/auth" onRefresh={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(screen.getByText("auth")).toBeInTheDocument();
  });

  it("calls onRefresh", () => {
    const onRefresh = vi.fn();
    renderWithI18n(
      <WikiUpdateNotification pagePath="a/b" onRefresh={onRefresh} onDismiss={vi.fn()} />,
    );
    fireEvent.click(screen.getByText(/refresh/i));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("calls onDismiss", () => {
    const onDismiss = vi.fn();
    renderWithI18n(
      <WikiUpdateNotification pagePath="a/b" onRefresh={vi.fn()} onDismiss={onDismiss} />,
    );
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[buttons.length - 1]);
    expect(onDismiss).toHaveBeenCalled();
  });
});
