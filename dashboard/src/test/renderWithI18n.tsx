import { type ReactElement, type ReactNode } from "react";
import { render, type RenderOptions } from "@testing-library/react";
import { TestI18nProvider } from "../i18n/context";

function I18nTestWrapper({ children }: { children: ReactNode }) {
  return <TestI18nProvider>{children}</TestI18nProvider>;
}

export function renderWithI18n(ui: ReactElement, options?: Omit<RenderOptions, "wrapper">) {
  return render(ui, { wrapper: I18nTestWrapper, ...options });
}
