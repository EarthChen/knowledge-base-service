import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WikiUpdateNotification from "../WikiUpdateNotification";

describe("WikiUpdateNotification", () => {
  it("shows page name", () => {
    render(
      <WikiUpdateNotification pagePath="user/auth" onRefresh={vi.fn()} onDismiss={vi.fn()} />,
    );
    expect(screen.getByText("auth")).toBeInTheDocument();
  });

  it("calls onRefresh", () => {
    const onRefresh = vi.fn();
    render(
      <WikiUpdateNotification pagePath="a/b" onRefresh={onRefresh} onDismiss={vi.fn()} />,
    );
    fireEvent.click(screen.getByText(/refresh/i));
    expect(onRefresh).toHaveBeenCalled();
  });

  it("calls onDismiss", () => {
    const onDismiss = vi.fn();
    render(
      <WikiUpdateNotification pagePath="a/b" onRefresh={vi.fn()} onDismiss={onDismiss} />,
    );
    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[buttons.length - 1]);
    expect(onDismiss).toHaveBeenCalled();
  });
});
