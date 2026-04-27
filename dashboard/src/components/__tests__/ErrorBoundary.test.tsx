import type { ReactElement } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TestI18nProvider } from "../../i18n/context";
import ErrorBoundary from "../ErrorBoundary";
import zh from "../../i18n/zh";

function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("test crash");
  return <div>ok</div>;
}

const withEn = (ui: ReactElement) => <TestI18nProvider locale="en">{ui}</TestI18nProvider>;

describe("ErrorBoundary", () => {
  it("renders children when no error", () => {
    render(
      withEn(
        <ErrorBoundary>
          <ThrowingChild shouldThrow={false} />
        </ErrorBoundary>,
      ),
    );
    expect(screen.getByText("ok")).toBeTruthy();
  });

  it("renders fallback on error (English from i18n)", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      withEn(
        <ErrorBoundary>
          <ThrowingChild shouldThrow={true} />
        </ErrorBoundary>,
      ),
    );
    expect(
      screen.getByText("Something went wrong", { exact: true }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("renders translated fallback in Chinese", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <TestI18nProvider locale="zh">
        <ErrorBoundary>
          <ThrowingChild shouldThrow={true} />
        </ErrorBoundary>
      </TestI18nProvider>,
    );
    expect(screen.getByText(zh.errorBoundary.defaultMessage, { exact: true })).toBeTruthy();
    expect(screen.getByRole("button", { name: zh.common.retry })).toBeTruthy();
  });

  it("renders custom fallback label", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      withEn(
        <ErrorBoundary fallbackLabel="Wiki failed">
          <ThrowingChild shouldThrow={true} />
        </ErrorBoundary>,
      ),
    );
    expect(screen.getByText("Wiki failed")).toBeTruthy();
  });

  it("recovers when retry is clicked", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      withEn(
        <ErrorBoundary>
          <ThrowingChild shouldThrow={true} />
        </ErrorBoundary>,
      ),
    );
    // Update to a non-throwing tree first while the boundary still shows the fallback.
    // Then retry clears error so the child render succeeds.
    rerender(
      withEn(
        <ErrorBoundary>
          <ThrowingChild shouldThrow={false} />
        </ErrorBoundary>,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(screen.getByText("ok")).toBeTruthy();
  });
});
