import { useState } from "react";
import { render, screen, act, waitFor, fireEvent } from "@testing-library/react";
import { describe, it, expect, afterEach, vi, beforeEach } from "vitest";
import { I18nProvider, TestI18nProvider, useI18n } from "../context";

const KEY = "kb_locale";

function Reader() {
  const { locale, t, setLocale } = useI18n();
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="label">{t.common.loading}</span>
      <button type="button" onClick={() => setLocale("zh")}>
        to zh
      </button>
    </div>
  );
}

describe("I18nProvider", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    document.documentElement.lang = "";
  });

  it("provides detectLocale, updates html lang, and persists setLocale", async () => {
    localStorage.setItem(KEY, "en");
    vi.stubGlobal("navigator", { language: "en-US" });
    render(
      <I18nProvider>
        <Reader />
      </I18nProvider>,
    );
    expect(screen.getByTestId("locale")).toHaveTextContent("en");
    await act(async () => {
      screen.getByRole("button", { name: "to zh" }).click();
    });
    expect(screen.getByTestId("locale")).toHaveTextContent("zh");
    expect(localStorage.getItem(KEY)).toBe("zh");
    await waitFor(() => {
      expect(document.documentElement.getAttribute("lang")).toBe("zh");
    });
    vi.unstubAllGlobals();
  });

  it("keeps context value referentially stable when parent re-renders without locale change", () => {
    vi.stubGlobal("navigator", { language: "en-US" });
    const refs: unknown[] = [];

    function Probe() {
      refs.push(useI18n());
      return null;
    }

    function Shell() {
      const [n, setN] = useState(0);
      return (
        <>
          <button type="button" data-testid="bump-i18n" onClick={() => setN((x) => x + 1)}>
            {n}
          </button>
          <I18nProvider>
            <Probe />
          </I18nProvider>
        </>
      );
    }

    render(<Shell />);

    const idxAfterMount = refs.length;
    const first = refs[idxAfterMount - 1];

    fireEvent.click(screen.getByTestId("bump-i18n"));

    const last = refs[refs.length - 1];
    expect(last).toBe(first);
    vi.unstubAllGlobals();
  });
});

describe("TestI18nProvider", () => {
  it("injects a fixed locale without setLocale side effects", () => {
    function Child() {
      const { locale } = useI18n();
      return <span data-testid="l">{locale}</span>;
    }
    render(
      <TestI18nProvider locale="en">
        <Child />
      </TestI18nProvider>,
    );
    expect(screen.getByTestId("l")).toHaveTextContent("en");
  });
});
